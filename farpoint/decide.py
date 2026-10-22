"""Client for the local Strands Decider server.

All calls go through ONE process-wide lock (the one inside
`patterns.reflex_gate.client`): upstream issue #17 means overlapping requests can return
each other's answers. `eval/spike_s1.py` and `eval/spike_s2.py` import `ask`, `_lock` and
`DECIDER_URL` from here.
"""
from __future__ import annotations

import os

from patterns.reflex_gate.client import _LOCK as _lock  # noqa: F401 - re-exported for eval/spike_s2.py
from patterns.reflex_gate.client import DeciderHttpClient

DECIDER_URL = os.environ.get("FARPOINT_DECIDER_URL", "http://127.0.0.1:8099/v1/systemone")
_client = DeciderHttpClient(DECIDER_URL)


def client() -> DeciderHttpClient:
    return _client


def ask(state, questions: dict, timeout: float = 30.0, images: list[str] | None = None) -> dict:
    return _client.ask(state, questions, images=images, timeout=timeout)
