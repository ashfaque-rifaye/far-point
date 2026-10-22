"""FastAPI server: serves the web workstream's build (web/dist) and the contract WebSocket.

No UI lives here. Security: bind 127.0.0.1 only (app.py refuses anything else), accept only
localhost Host headers, and check the WebSocket Origin against an allowlist so other browser
tabs cannot hijack the socket (it has no auth).
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

log = logging.getLogger("farpoint.dashboard")

ALLOWED_ORIGINS = frozenset({
    "http://127.0.0.1:8765", "http://localhost:8765",
    "http://127.0.0.1:5173", "http://localhost:5173",
})
ALLOWED_HOSTS = ["127.0.0.1", "localhost"]
UI_MISSING = "UI not built yet: the web workstream builds web/dist"


def create_app(runtime, manage_lifecycle: bool = True, web_dist: Path | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if manage_lifecycle:
            await asyncio.to_thread(runtime.start)
        try:
            yield
        finally:
            if manage_lifecycle:
                await asyncio.to_thread(runtime.stop)

    app = FastAPI(title="Far Point", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=ALLOWED_HOSTS)
    app.state.runtime = runtime

    @app.websocket("/ws")
    async def ws_endpoint(websocket: WebSocket):
        origin = websocket.headers.get("origin")
        if origin is not None and origin not in ALLOWED_ORIGINS:
            log.warning("rejected WebSocket from origin %s", origin)
            await websocket.close(code=1008)
            return
        await websocket.accept()
        loop = asyncio.get_running_loop()
        q = runtime.bus.subscribe(loop)

        async def pump():
            while True:
                env = await q.get()
                await websocket.send_json(env)

        sender = None
        try:
            for env in runtime.bus.connect_burst():
                await websocket.send_json(env)
            sender = asyncio.create_task(pump())
            while True:
                raw = await websocket.receive_text()
                # Commands can block (calibration waits on the camera thread): run off the loop.
                await asyncio.to_thread(runtime.handle_raw, raw)
        except WebSocketDisconnect:
            pass
        finally:
            if sender is not None:
                sender.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await sender
            if runtime.bus.unsubscribe(q) == 0:
                runtime.broker.deny_all()  # contract: a dropped socket counts as "no"

    dist = Path(web_dist or runtime.settings.web_dist)
    if (dist / "index.html").exists():
        app.mount("/", StaticFiles(directory=dist, html=True), name="ui")
    else:
        @app.get("/", response_class=PlainTextResponse)
        async def ui_missing() -> str:
            return UI_MISSING

    return app
