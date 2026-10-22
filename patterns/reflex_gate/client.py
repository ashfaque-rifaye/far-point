"""HTTP client for a local Strands Decider server (`strands-decider serve`).

Every call in the process goes through ONE lock: upstream issue #17 means overlapping
requests can return each other's answers.
"""
from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit, urlunsplit

DEFAULT_URL = "http://127.0.0.1:8099/v1/systemone"
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}

_LOCK = threading.Lock()


class DeciderHttpClient:
    def __init__(self, url: str = DEFAULT_URL, timeout: float = 30.0):
        self.url = url
        self.timeout = timeout
        parts = urlsplit(url)
        self.host = parts.hostname or ""
        self.health_url = urlunsplit((parts.scheme, parts.netloc, "/health", "", ""))

    @property
    def is_local(self) -> bool:
        return self.host in LOCAL_HOSTS

    def ask(self, state, questions: dict, images: list[str] | None = None, timeout: float | None = None) -> dict:
        """POST one request. Returns the server JSON (answers, usage, latency_ms).

        Images are only ever sent to a localhost server.
        """
        if images and not self.is_local:
            raise ValueError(f"refusing to send images to non-local Decider host {self.host!r}")
        body = {"state": state if isinstance(state, str) else json.dumps(state), "questions": questions}
        if images:
            body["images"] = list(images)
        req = urllib.request.Request(
            self.url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}
        )
        with _LOCK:
            t0 = time.perf_counter()
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as resp:
                out = json.loads(resp.read())
            out.setdefault("client_ms", round((time.perf_counter() - t0) * 1000, 1))
        return out

    def health(self, timeout: float = 5.0) -> bool:
        info = self.health_info(timeout)
        return bool(info) and info.get("status") == "ok"

    def health_info(self, timeout: float = 5.0, retries: int = 1) -> dict | None:
        for attempt in range(retries + 1):
            try:
                with urllib.request.urlopen(self.health_url, timeout=timeout) as resp:
                    return json.loads(resp.read())
            except (OSError, ValueError, urllib.error.URLError):
                if attempt < retries:
                    time.sleep(0.5)
        return None
