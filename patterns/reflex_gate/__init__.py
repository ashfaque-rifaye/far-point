"""REUSABLE DECISION PATTERN: Reflex Gate

Fast, local, repeated decisions with Strands Decider 2B, wired into a Strands Agent:

1. Each rule of a priority-ordered rulebook becomes one `noul` question
   ("does rule N apply right now?"). One request asks all of them plus `interrupt_ok`.
2. Code applies the priority order and a confidence policy (fire / unsure / clear,
   escalate the unsure ones, fail quiet).
3. Tools run through `agent.tool.<name>()`, so Strands interventions gate them:
   `InterruptGate` before interruptive tools, `ConfirmGate` before persistent ones.

Standalone: imports only `strands`, `pydantic` and the standard library.
"""
from .client import DeciderHttpClient
from .fakes import FakeDecider, ScriptedModel, contains_image, oracle
from .gate import ConfirmGate, InterruptGate
from .policy import RuleVerdict, Selection, Thresholds, classify, next_action_payload, select
from .questions import INTERRUPT_OK, Rule, build_questions, question_key, rule_question

__all__ = [
    "ConfirmGate",
    "DeciderHttpClient",
    "FakeDecider",
    "INTERRUPT_OK",
    "InterruptGate",
    "Rule",
    "RuleVerdict",
    "ScriptedModel",
    "Selection",
    "Thresholds",
    "build_questions",
    "classify",
    "contains_image",
    "next_action_payload",
    "oracle",
    "question_key",
    "rule_question",
    "select",
]
