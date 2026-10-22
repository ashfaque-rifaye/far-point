"""Confidence policy: turn per-rule probabilities into one action, in code.

The Decider says how likely each rule applies. This module applies the priority order:

- a rule FIRES at p >= fire_p, is CLEAR at p <= clear_p, and is UNSURE in between;
- walk the rules in priority order and take the first one that fires, unless a
  higher-priority rule is unsure;
- unsure rules above the first firing rule go to `escalate` (a slower, smarter judge);
  if escalation is off, fails or returns None, stay quiet ("fail quiet");
- the ask tool is rate limited in code (one per `ask_cooldown_s`).
"""
from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Literal

from .questions import Rule, question_key

State = Literal["fires", "unsure", "clear"]
Policy = Literal["act", "quiet", "ask"]
Escalate = Callable[[list[Rule]], dict[int, bool | None]]


@dataclass(frozen=True)
class Thresholds:
    fire_p: float = 0.65
    clear_p: float = 0.35
    interrupt_p: float = 0.5
    ask_cooldown_s: float = 1800.0


@dataclass
class RuleVerdict:
    n: int
    tool: str
    p: float | None
    state: State
    escalated: bool | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Selection:
    tool: str | None
    rule_n: int | None
    policy: Policy
    verdicts: list[RuleVerdict]
    unsure: list[int]
    interrupt_p: float | None
    next_action: dict
    reason: str
    escalation: dict | None = None


def noul_p(answers: dict, key: str) -> float | None:
    a = answers.get(key)
    if not isinstance(a, dict) or a.get("noul") is None:
        return None
    return min(1.0, max(0.0, float(a["noul"])))


def classify(p: float | None, th: Thresholds) -> State:
    if p is None:
        return "unsure"
    if p >= th.fire_p:
        return "fires"
    if p <= th.clear_p:
        return "clear"
    return "unsure"


def next_action_payload(verdicts: list[RuleVerdict], choice: str | None) -> dict:
    """Contract-shaped `next_action`: probs over {tool: max p} plus none = prod(1 - p)."""
    raw: dict[str, float] = {}
    none = 1.0
    for v in verdicts:
        p = 0.5 if v.p is None else v.p
        raw[v.tool] = max(raw.get(v.tool, 0.0), p)
        none *= 1.0 - p
    raw["none"] = none
    total = sum(raw.values()) or 1.0
    probs = {k: round(v / total, 4) for k, v in raw.items()}
    key = choice or "none"
    return {"choice": key, "confidence": probs.get(key, 0.0), "probs": probs}


def _fmt(p: float | None) -> str:
    return "n/a" if p is None else f"{p:.2f}"


def select(
    rules: list[Rule],
    answers: dict,
    thresholds: Thresholds = Thresholds(),
    escalate: Escalate | None = None,
    now: float | None = None,
    last_ask_t: float | None = None,
    ask_tool: str = "ask_user",
) -> Selection:
    """Pick at most one tool from per-rule nouls. See the module docstring."""
    now = time.time() if now is None else now
    ordered = sorted(rules, key=lambda r: r.n)
    by_n = {r.n: r for r in ordered}
    verdicts = []
    for r in ordered:
        p = noul_p(answers, question_key(r.n))
        verdicts.append(RuleVerdict(r.n, r.tool, p, classify(p, thresholds)))
    interrupt_p = noul_p(answers, "interrupt_ok")

    def allowed(v: RuleVerdict) -> bool:
        if v.tool == ask_tool and last_ask_t is not None:
            return now - last_ask_t >= thresholds.ask_cooldown_s
        return True

    # First pass: the first firing rule, and any unsure rules that outrank it.
    unsure_above: list[RuleVerdict] = []
    chosen: RuleVerdict | None = None
    for v in verdicts:
        if not allowed(v):
            continue
        if v.state == "fires":
            chosen = v
            break
        if v.state == "unsure":
            unsure_above.append(v)
    reason = f"rule {chosen.n} fires (p={_fmt(chosen.p)})" if chosen else "no rule applies"

    escalation = None
    if unsure_above:
        result: dict[int, bool | None] = {}
        error = None
        t0 = time.perf_counter()
        if escalate is not None:
            try:
                result = escalate([by_n[v.n] for v in unsure_above]) or {}
            except Exception as e:  # noqa: BLE001 - an escalation failure means fail quiet
                error = type(e).__name__
                result = {}
            escalation = {
                "rules": [v.n for v in unsure_above],
                "verdicts": {str(v.n): result.get(v.n) for v in unsure_above},
                "latency_ms": round((time.perf_counter() - t0) * 1000, 1),
                "error": error,
            }
        for v in unsure_above:
            v.escalated = result.get(v.n)

        # Second pass with the escalated verdicts.
        chosen = None
        reason = "no rule applies"
        for v in verdicts:
            if not allowed(v):
                continue
            if v.state == "fires":
                chosen = v
                reason = f"rule {v.n} fires (p={_fmt(v.p)}); the unsure rules above it were cleared"
                break
            if v.state != "unsure":
                continue
            if v.escalated is True:
                chosen = v
                reason = f"rule {v.n} unsure (p={_fmt(v.p)}); escalation says it applies"
                break
            if v.escalated is False:
                continue
            why = "escalation unavailable" if escalate is None else "escalation gave no verdict"
            reason = f"rule {v.n} unsure (p={_fmt(v.p)}) and {why}: fail quiet"
            break

    if chosen is None:
        tool, rule_n, policy = None, None, "quiet"
    else:
        tool, rule_n = chosen.tool, chosen.n
        policy = "ask" if chosen.tool == ask_tool else "act"
    return Selection(
        tool=tool,
        rule_n=rule_n,
        policy=policy,
        verdicts=verdicts,
        unsure=[v.n for v in unsure_above],
        interrupt_p=interrupt_p,
        next_action=next_action_payload(verdicts, tool),
        reason=reason,
        escalation=escalation,
    )
