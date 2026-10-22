"""Typed Decider questions for the Reflex Gate pattern.

Each rule becomes one `noul` question ("does rule N apply right now?") with explicit
true/false criteria. One request carries every candidate rule plus `interrupt_ok`, all
over the same rendered state, so a whole decision costs one Decider call.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Rule:
    """One plain-English rule that maps to exactly one tool.

    `n` is the priority (1 = highest). Code applies the priority order; the Decider only
    judges whether each rule applies.
    """

    n: int
    tool: str
    text: str
    when_true: str
    when_false: str


def question_key(n: int) -> str:
    return f"rule_{n}"


def rule_question(rule: Rule) -> dict:
    return {
        "type": "noul",
        "instructions": f"Does rule {rule.n} apply right now? Rule {rule.n}: {rule.text}",
        "criteria": {"true": rule.when_true, "false": rule.when_false},
    }


# Copied from eval/s1_questions.py V2 (scored 100% on the held-out S1 set).
INTERRUPT_OK = {
    "type": "noul",
    "instructions": "Read the Activity line. Is it OK to interrupt the user with a prompt right now?",
    "criteria": {
        "true": "Activity says idle, between tasks, or just switched windows",
        "false": "Activity says video call, presenting or screen sharing, typing in a burst, or fullscreen video",
    },
}


def build_questions(rules: list[Rule], include_interrupt: bool = True) -> dict:
    """Questions for one request: `rule_<n>` per rule, plus `interrupt_ok`."""
    qs = {question_key(r.n): rule_question(r) for r in rules}
    if include_interrupt:
        qs["interrupt_ok"] = {**INTERRUPT_OK, "criteria": dict(INTERRUPT_OK["criteria"])}
    return qs
