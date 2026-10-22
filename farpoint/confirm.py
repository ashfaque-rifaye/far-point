"""ConfirmBroker: asks the human (via the UI's confirm modal) and waits for the answer.

Fail closed: a timeout, a dropped socket or no connected UI all count as "no".
"""
from __future__ import annotations

import itertools
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass
class _Pending:
    title: str
    detail: str
    event: threading.Event = field(default_factory=threading.Event)
    answer: bool | None = None
    on_answer: Callable[[bool], None] | None = None


class ConfirmBroker:
    def __init__(self, bus, deny_without_client: bool = True):
        self.bus = bus
        self.deny_without_client = deny_without_client
        self._lock = threading.Lock()
        self._pending: dict[str, _Pending] = {}
        self._tokens: dict[str, float] = {}
        self._ids = itertools.count(1)

    def _no_client(self) -> bool:
        return self.deny_without_client and self.bus.subscriber_count() == 0

    def _open(self, title: str, detail: str, on_answer=None) -> str:
        rid = f"c_{next(self._ids):06d}"
        with self._lock:
            self._pending[rid] = _Pending(title, detail, on_answer=on_answer)
        self.bus.publish("confirm_request", {"request_id": rid, "title": title, "detail": detail})
        return rid

    def request(self, title: str, detail: str, timeout_s: float = 120.0) -> bool:
        """Block the calling (worker) thread until the user answers. Timeout = deny."""
        if self._no_client():
            return False
        rid = self._open(title, detail)
        p = self._pending[rid]
        p.event.wait(timeout_s)
        with self._lock:
            self._pending.pop(rid, None)
        return bool(p.answer)

    def request_async(self, title: str, detail: str, on_answer: Callable[[bool], None]) -> str | None:
        """Ask without blocking. `on_answer(bool)` runs on the thread that resolves it.

        Returns the request id, or None (and calls on_answer(False)) when no UI is connected.
        """
        if self._no_client():
            on_answer(False)
            return None
        return self._open(title, detail, on_answer=on_answer)

    def resolve(self, request_id: str, approve: bool) -> bool:
        with self._lock:
            p = self._pending.get(request_id)
            if p is None or p.event.is_set():
                return False
            p.answer = bool(approve)
            p.event.set()
            if p.on_answer is not None:
                self._pending.pop(request_id, None)
        if p.on_answer is not None:
            p.on_answer(bool(approve))
        return True

    def deny_all(self) -> int:
        with self._lock:
            ids = [rid for rid, p in self._pending.items() if not p.event.is_set()]
        for rid in ids:
            self.resolve(rid, False)
        return len(ids)

    def pending_ids(self) -> list[str]:
        with self._lock:
            return [rid for rid, p in self._pending.items() if not p.event.is_set()]

    # ---- single-use pre-approval tokens (UI approve_* commands) ---------------------
    def preapprove(self, key: str, ttl_s: float = 30.0) -> None:
        with self._lock:
            self._tokens[key] = time.monotonic() + ttl_s

    def consume(self, key: str) -> bool:
        with self._lock:
            exp = self._tokens.pop(key, None)
        return exp is not None and time.monotonic() <= exp
