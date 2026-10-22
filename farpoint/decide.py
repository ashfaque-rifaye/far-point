"""Client for the local Strands Decider server.

All calls are serialized behind a lock: upstream issue #17 means overlapping
requests can return each other's answers.
"""
from __future__ import annotations

import json
import os
import threading
import urllib.request

DECIDER_URL = os.environ.get("FARPOINT_DECIDER_URL", "http://127.0.0.1:8099/v1/systemone")
_lock = threading.Lock()


def ask(state, questions: dict, timeout: float = 30.0) -> dict:
    body = json.dumps({"state": state if isinstance(state, str) else json.dumps(state), "questions": questions}).encode()
    req = urllib.request.Request(DECIDER_URL, data=body, headers={"Content-Type": "application/json"})
    with _lock:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
