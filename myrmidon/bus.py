"""Event bus: worker threads publish contract events; WebSocket clients subscribe.

FastAPI/uvicorn owns the asyncio loop. Publishers run on worker threads, so events are
handed to each subscriber's asyncio.Queue with `loop.call_soon_threadsafe`.
"""
from __future__ import annotations

import asyncio
import json
import threading
import time
from collections.abc import Callable
from pathlib import Path

SIGNALS_MIN_INTERVAL_S = 0.1  # <= 10 Hz
QUEUE_MAX = 2000


class EventRecorder:
    """Writes every published envelope as JSONL (numbers and text only, never images)."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._f = self.path.open("a", encoding="utf-8")
        self._lock = threading.Lock()

    def write(self, env: dict) -> None:
        with self._lock:
            if self._f.closed:
                return
            self._f.write(json.dumps(env, separators=(",", ":")) + "\n")
            self._f.flush()

    def close(self) -> None:
        with self._lock:
            self._f.close()


class EventBus:
    def __init__(self, recorder: EventRecorder | None = None, clock_ms: Callable[[], int] | None = None,
                 validate: bool = False):
        self.recorder = recorder
        self.clock_ms = clock_ms or (lambda: int(time.time() * 1000))
        self.validate = validate
        self._lock = threading.RLock()
        self._subs: list[tuple[asyncio.AbstractEventLoop, asyncio.Queue]] = []
        self._listeners: list[Callable[[dict], None]] = []
        self._latest: dict[str, dict] = {}
        self._proposals: dict[str, dict] = {}
        self._last_signals = 0.0
        self.published = 0

    # ---- publishing -----------------------------------------------------------------
    def publish(self, type_: str, data: dict, force: bool = False) -> dict | None:
        if type_ == "signals" and not force:
            now = time.monotonic()
            if now - self._last_signals < SIGNALS_MIN_INTERVAL_S:
                return None
            self._last_signals = now
        env = {"v": 1, "type": type_, "t": self.clock_ms(), "data": data}
        if self.validate:
            from .contract import validate_event
            validate_event(env)
        with self._lock:
            if type_ in ("hello", "doctrine", "stats"):
                self._latest[type_] = env
            elif type_ == "proposal":
                if data.get("status") == "pending":
                    self._proposals[data["id"]] = env
                else:
                    self._proposals.pop(data.get("id"), None)
            subs = list(self._subs)
            listeners = list(self._listeners)
            self.published += 1
        if self.recorder is not None:
            self.recorder.write(env)
        for loop, q in subs:
            try:
                loop.call_soon_threadsafe(_put, q, env)
            except RuntimeError:  # loop closed
                self.unsubscribe(q)
        for fn in listeners:
            fn(env)
        return env

    def toast(self, level: str, text: str) -> None:
        self.publish("toast", {"level": level, "text": text})

    # ---- subscribers -----------------------------------------------------------------
    def subscribe(self, loop: asyncio.AbstractEventLoop) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=QUEUE_MAX)
        with self._lock:
            self._subs.append((loop, q))
        return q

    def unsubscribe(self, q: asyncio.Queue) -> int:
        with self._lock:
            self._subs = [(l, s) for l, s in self._subs if s is not q]
            return len(self._subs)

    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subs)

    def add_listener(self, fn: Callable[[dict], None]) -> None:
        with self._lock:
            self._listeners.append(fn)

    def remove_listener(self, fn: Callable[[dict], None]) -> None:
        with self._lock:
            self._listeners = [f for f in self._listeners if f is not fn]

    def latest(self, type_: str) -> dict | None:
        with self._lock:
            return self._latest.get(type_)

    def pending_proposals(self) -> list[dict]:
        with self._lock:
            return list(self._proposals.values())

    def connect_burst(self) -> list[dict]:
        """Contract step 2: hello, doctrine, pending proposals, stats."""
        with self._lock:
            out = []
            if "hello" in self._latest:
                out.append(self._latest["hello"])
            if "doctrine" in self._latest:
                out.append(self._latest["doctrine"])
            out.extend(self._proposals.values())
            if "stats" in self._latest:
                out.append(self._latest["stats"])
            return out


def _put(q: asyncio.Queue, env: dict) -> None:
    try:
        q.put_nowait(env)
    except asyncio.QueueFull:
        try:
            q.get_nowait()  # drop the oldest frame for a slow client
            q.put_nowait(env)
        except (asyncio.QueueEmpty, asyncio.QueueFull):
            pass
