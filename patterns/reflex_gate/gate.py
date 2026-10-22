"""Strands InterventionHandlers that gate tool calls.

`InterruptGate` sits before interruptive tools. It asks the Decider "is it OK to interrupt
right now?" (or reuses an `interrupt_ok` answer the loop already got in its batched
request, via `prime`) and returns `Proceed` or `Deny`.

`ConfirmGate` sits before persistent or outbound tools. It gets the human's answer first
(from a UI, a CLI, a token) and returns `Confirm(prompt, response=answer)`, so Strands'
own Confirm evaluation runs. A Confirm without a response raises "cannot raise interrupt
in direct tool call" on `agent.tool.X()` calls, which is why the answer is always
supplied up front.

Both are fail-closed (`on_error = "deny"`).
"""
from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterable

from strands.interventions import Confirm, Deny, InterventionHandler, Proceed

from .policy import Thresholds
from .questions import INTERRUPT_OK


class InterruptGate(InterventionHandler):
    name = "interrupt-gate"
    on_error = "deny"

    def __init__(self, client, state_provider: Callable[[], str], interruptive_tools: Iterable[str],
                 thresholds: Thresholds = Thresholds()):
        self.client = client
        self.state_provider = state_provider
        self.tools = frozenset(interruptive_tools)
        self.thresholds = thresholds
        self.last: dict = {"name": "InterruptGate", "verdict": None, "p": None}
        self._primed: tuple[float, float] | None = None
        self._lock = threading.Lock()

    def prime(self, p: float | None, ttl_s: float = 3.0) -> None:
        """Reuse an `interrupt_ok` answer from the loop's batched request (single use)."""
        with self._lock:
            self._primed = None if p is None else (float(p), time.monotonic() + ttl_s)

    def _take_primed(self) -> float | None:
        with self._lock:
            primed, self._primed = self._primed, None
        if primed and time.monotonic() <= primed[1]:
            return primed[0]
        return None

    def before_tool_call(self, event, **kwargs):
        tool = event.tool_use["name"]
        if tool not in self.tools:
            return Proceed()
        p = self._take_primed()
        if p is None:
            resp = self.client.ask(self.state_provider(), {"interrupt_ok": INTERRUPT_OK})
            p = float(resp["answers"]["interrupt_ok"]["noul"])
        if p >= self.thresholds.interrupt_p:
            self.last = {"name": "InterruptGate", "verdict": "proceed", "p": round(p, 4)}
            return Proceed(reason=f"p={p:.2f}")
        self.last = {"name": "InterruptGate", "verdict": "deny", "p": round(p, 4)}
        return Deny(reason=f"not a good moment to interrupt (p={p:.2f})")


PromptFn = Callable[[dict], str]
AskHuman = Callable[[str, str, dict], bool]


class ConfirmGate(InterventionHandler):
    name = "confirm-gate"
    on_error = "deny"

    def __init__(self, tools: dict[str, PromptFn], ask_human: AskHuman):
        self.tools = dict(tools)
        self.ask_human = ask_human
        self.last: dict = {"name": "Confirm", "verdict": None, "p": None}

    def before_tool_call(self, event, **kwargs):
        tool = event.tool_use["name"]
        if tool not in self.tools:
            return Proceed()
        args = dict(event.tool_use.get("input") or {})
        prompt = self.tools[tool](args)
        answer = bool(self.ask_human(tool, prompt, args))
        self.last = {"name": "Confirm", "verdict": "proceed" if answer else "deny", "p": None, "tool": tool}
        return Confirm(prompt=prompt, response=answer)
