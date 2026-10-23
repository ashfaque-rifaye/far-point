"""Myrmidon entrypoint (localhost only).

  python -m myrmidon.app --mode live
  python -m myrmidon.app --mode replay --trace myrmidon\\replay\\demo_session.jsonl --fake-decider --no-bedrock
  python -m myrmidon.app --events <recorded bus trace.jsonl>

Restore on exit: uvicorn runs the FastAPI lifespan shutdown on Ctrl+C, which stops the
threads and calls `Actuators.restore_all()`; `atexit` covers other exits, and the restore
journal covers crashes on the next start.
"""
from __future__ import annotations

import logging
import sys

from .config import ALLOWED_HOST, parse_args


def main(argv: list[str] | None = None) -> int:
    settings = parse_args(argv)
    if settings.host != ALLOWED_HOST:
        print(f"refusing to bind to {settings.host!r}: Myrmidon has no auth and binds to {ALLOWED_HOST} only",
              file=sys.stderr)
        return 2
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    import uvicorn

    from .dashboard import create_app
    from .runtime import Runtime

    runtime = Runtime(settings)
    app = create_app(runtime)
    uvicorn.run(app, host=ALLOWED_HOST, port=settings.port, log_level="info", ws_ping_interval=20)
    return 0


if __name__ == "__main__":
    sys.exit(main())
