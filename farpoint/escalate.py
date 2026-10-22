"""Escalation of UNSURE rules to Amazon Nova Lite (Bedrock), text only.

When a higher-priority rule is in the Decider's unsure band (0.35-0.65), the policy asks
Nova Lite about those rules with the same rendered TEXT state. No images, ever. Rate
limited, budgeted, and time-boxed; any failure returns None for every rule, and the
policy then stays quiet.
"""
from __future__ import annotations

import os
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from datetime import datetime

from pydantic import BaseModel, Field

from patterns.reflex_gate import Rule

DEFAULT_MODEL = "us.amazon.nova-lite-v1:0"
SYSTEM_PROMPT = (
    "You check a few rules against a measured state for Far Point, a screen-habits assistant. "
    "Code computed every number in the state and wrote the verdict at the end of each line; trust those "
    "verdict words. For each listed rule, decide whether it applies right now, using its true/false criteria. "
    "Answer only through the RuleJudgements tool, one judgement per listed rule. Never give medical advice."
)


class RuleJudgement(BaseModel):
    n: int = Field(description="The rule number")
    applies: bool = Field(description="True if the rule applies to the measured state right now")


class RuleJudgements(BaseModel):
    """One judgement per listed rule."""

    judgements: list[RuleJudgement]


def render_prompt(state_text: str, rules: list[Rule]) -> str:
    lines = ["Measured state:", state_text, "", "Rules to check:"]
    for r in rules:
        lines += [f"Rule {r.n}: {r.text}", f"  applies (true) when: {r.when_true}",
                  f"  does not apply (false) when: {r.when_false}"]
    lines += ["", f"Return judgements for rules {', '.join(str(r.n) for r in rules)}."]
    return "\n".join(lines)


class NovaEscalator:
    def __init__(self, model_id: str = DEFAULT_MODEL, region: str | None = None, stats=None, moments=None,
                 min_interval_s: float = 10.0, daily_budget: int = 300, timeout_s: float = 4.0,
                 model_factory=None, clock=time.time):
        self.model_id = model_id
        self.region = region or os.environ.get("AWS_REGION", "us-east-1")
        self.stats = stats
        self.moments = moments
        self.min_interval_s = min_interval_s
        self.daily_budget = daily_budget
        self.timeout_s = timeout_s
        self.model_factory = model_factory
        self.clock = clock
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="farpoint-escalate")
        self._inflight: Future | None = None
        self._lock = threading.Lock()
        self._last_t: float | None = None
        self._day: str | None = None
        self._count = 0
        self.last: dict | None = None

    def _model(self):
        if self.model_factory is not None:
            return self.model_factory()
        from strands.models import BedrockModel
        return BedrockModel(model_id=self.model_id, region_name=self.region, max_tokens=300, temperature=0.0)

    def _run(self, prompt: str) -> tuple[dict[int, bool], float]:
        from strands import Agent
        agent = Agent(model=self._model(), system_prompt=SYSTEM_PROMPT, callback_handler=None,
                      structured_output_model=RuleJudgements, name="farpoint-escalator")
        t0 = time.perf_counter()
        result = agent(prompt)
        latency_ms = (time.perf_counter() - t0) * 1000
        usage = result.metrics.accumulated_usage or {}
        if self.stats is not None:  # counted here so a timed-out call still counts
            self.stats.record_bedrock(max(1, result.metrics.cycle_count), int(usage.get("totalTokens", 0)),
                                      who="escalate", model=self.model_id,
                                      input_tokens=int(usage.get("inputTokens", 0)),
                                      output_tokens=int(usage.get("outputTokens", 0)))
        so = result.structured_output
        verdicts = {j.n: bool(j.applies) for j in (so.judgements if so else [])}
        return verdicts, latency_ms

    def _skip(self, rules: list[Rule], why: str, decider_p: dict | None) -> dict[int, None]:
        self.last = {"model": self.model_id, "skipped": why, "verdicts": {}, "latency_ms": 0}
        if self.moments is not None:
            self.moments.log("unsure", f"escalation skipped: {why}", rules=[r.n for r in rules],
                             decider_p=decider_p or {})
        return {r.n: None for r in rules}

    def __call__(self, state_text: str, rules: list[Rule], decider_p: dict | None = None) -> dict[int, bool | None]:
        assert isinstance(state_text, str), "escalation is text-only"
        if not rules:
            return {}
        now = self.clock()
        with self._lock:
            day = datetime.fromtimestamp(now).strftime("%Y-%m-%d")
            if day != self._day:
                self._day, self._count = day, 0
            if self._count >= self.daily_budget:
                return self._skip(rules, "daily budget reached", decider_p)
            if self._last_t is not None and now - self._last_t < self.min_interval_s:
                return self._skip(rules, "rate limited", decider_p)
            if self._inflight is not None and not self._inflight.done():
                return self._skip(rules, "previous call still running", decider_p)
            self._last_t = now
            self._count += 1
            fut = self._pool.submit(self._run, render_prompt(state_text, rules))
            self._inflight = fut
        try:
            verdicts, latency_ms = fut.result(timeout=self.timeout_s)
        except FutureTimeout:
            return self._skip(rules, f"timed out after {self.timeout_s:.0f} s", decider_p)
        except Exception as e:  # noqa: BLE001 - Bedrock down, throttled, bad output
            return self._skip(rules, f"error {type(e).__name__}", decider_p)
        out = {r.n: verdicts.get(r.n) for r in rules}
        self.last = {"model": self.model_id, "latency_ms": round(latency_ms, 1),
                     "verdicts": {str(k): v for k, v in out.items()}}
        if self.moments is not None:
            self.moments.log("escalated", "Nova Lite judged unsure rules", rules=[r.n for r in rules],
                             decider_p=decider_p or {}, nova={str(k): v for k, v in out.items()},
                             latency_ms=round(latency_ms, 1))
        return out

    def close(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)
