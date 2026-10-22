"""Test doubles: a fake Decider and a scripted Strands model. No GPU, no AWS.

`FakeDecider(fn)` answers every noul with `fn(state, name, question)` and returns the
same response shape as `strands-decider serve`.

`ScriptedModel(script)` is a `strands.models.Model` that replays scripted turns as
Bedrock-style stream events and records every request in `.calls`.
`ScriptedModel(script=[], fail_if_called=True)` raises on any call, which proves a code
path never invokes the model.
"""
from __future__ import annotations

import copy
import itertools
import json
import threading
import time
from collections.abc import AsyncGenerator, AsyncIterable, Callable
from typing import Any

from strands.models import Model

NoulFn = Callable[[str, str, dict], float]


class FakeDecider:
    """Duck-types `DeciderHttpClient` (`ask`, `health`)."""

    model = "FAKE oracle (tests/demo)"

    def __init__(self, fn: NoulFn, latency_ms: float = 5.0, fail: Exception | None = None):
        self.fn = fn
        self.latency_ms = latency_ms
        self.fail = fail
        self.calls: list[dict] = []
        self._lock = threading.Lock()

    def ask(self, state, questions: dict, images: list[str] | None = None, timeout: float | None = None) -> dict:
        with self._lock:
            self.calls.append({"state": state, "questions": questions, "images": images})
            if self.fail is not None:
                raise self.fail
            answers = {}
            for name, q in questions.items():
                if q.get("type", "noul") != "noul":
                    raise ValueError(f"FakeDecider answers noul questions only, got {q.get('type')!r}")
                p = float(self.fn(state if isinstance(state, str) else json.dumps(state), name, q))
                answers[name] = {"type": "noul", "noul": min(1.0, max(0.0, p))}
            return {
                "model": self.model,
                "answers": answers,
                "usage": {"input_tokens": len(str(state)) // 4, "output_tokens": 0},
                "latency_ms": self.latency_ms,
            }

    def health(self, timeout: float = 2.0) -> bool:
        return self.fail is None

    def health_info(self, timeout: float = 2.0) -> dict | None:
        return {"status": "ok", "model": self.model, "device": "cpu", "vision": False} if self.fail is None else None


class ScriptedModel(Model):
    """Replays scripted turns: `{"tool": name, "input": {...}}` or `{"text": "..."}`."""

    def __init__(self, script: list[dict] | None = None, fail_if_called: bool = False,
                 usage: dict | None = None):
        self.script = list(script or [])
        self.fail_if_called = fail_if_called
        self.usage = usage or {"inputTokens": 120, "outputTokens": 30, "totalTokens": 150}
        self.calls: list[dict] = []
        self.attempts = 0
        self.config: dict[str, Any] = {"model_id": "scripted"}
        self._ids = itertools.count(1)

    def update_config(self, **model_config: Any) -> None:
        self.config.update(model_config)

    def get_config(self) -> Any:
        return self.config

    async def structured_output(self, output_model, prompt, system_prompt=None, **kwargs) -> AsyncGenerator[dict, None]:
        self.attempts += 1
        if self.fail_if_called:
            raise AssertionError("ScriptedModel was called but fail_if_called=True")
        self.calls.append({"messages": copy.deepcopy(prompt), "system_prompt": system_prompt, "structured": True})
        turn = self.script.pop(0)
        yield {"output": output_model(**turn["input"])}

    async def stream(self, messages, tool_specs=None, system_prompt=None, **kwargs) -> AsyncIterable[dict]:
        self.attempts += 1
        if self.fail_if_called:
            raise AssertionError("ScriptedModel was called but fail_if_called=True")
        self.calls.append({
            "messages": copy.deepcopy(messages),
            "system_prompt": system_prompt,
            "tools": [t.get("name") for t in (tool_specs or [])],
        })
        if not self.script:
            raise AssertionError("ScriptedModel ran out of scripted turns")
        turn = self.script.pop(0)
        yield {"messageStart": {"role": "assistant"}}
        if "tool" in turn:
            tool_use_id = f"tooluse_scripted_{next(self._ids)}"
            yield {"contentBlockStart": {"start": {"toolUse": {"toolUseId": tool_use_id, "name": turn["tool"]}}}}
            yield {"contentBlockDelta": {"delta": {"toolUse": {"input": json.dumps(turn.get("input", {}))}}}}
            yield {"contentBlockStop": {}}
            stop = "tool_use"
        else:
            yield {"contentBlockStart": {"start": {}}}
            yield {"contentBlockDelta": {"delta": {"text": turn.get("text", "")}}}
            yield {"contentBlockStop": {}}
            stop = "end_turn"
        yield {"messageStop": {"stopReason": stop}}
        yield {"metadata": {"usage": dict(self.usage), "metrics": {"latencyMs": 1}}}


def _walk(obj):
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v)


def contains_image(calls: list[dict]) -> bool:
    """True if any recorded request holds an image/document block or base64 image bytes."""
    for call in calls:
        for d in _walk(call.get("messages", [])):
            if "image" in d or "document" in d or "video" in d:
                return True
        blob = json.dumps(call.get("messages", []), default=str)
        if "/9j/4" in blob or "iVBORw0KGgo" in blob or "data:image" in blob:
            return True
    return False


def oracle(predicate_for: Callable[[str], bool | None], interrupt_ok: Callable[[], bool],
           yes: float = 0.92, no: float = 0.06) -> NoulFn:
    """Build a crisp FakeDecider fn from code predicates.

    `predicate_for(question_name)` returns True/False for `rule_<n>` keys (None = unsure, 0.5).
    """
    def fn(state: str, name: str, question: dict) -> float:
        if name == "interrupt_ok":
            return yes if interrupt_ok() else no
        v = predicate_for(name)
        if v is None:
            return 0.5
        return yes if v else no
    return fn


def now_ms() -> int:
    return int(time.time() * 1000)
