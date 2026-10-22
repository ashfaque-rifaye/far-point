from strands_decider.schema import SystemOneRequest

from patterns.reflex_gate import INTERRUPT_OK, Rule, build_questions, rule_question

RULES = [
    Rule(1, "enlarge_text", "Viewing distance says too close.", "the line says too close", "the line says not too close"),
    Rule(2, "far_look_break", "Near-work bout says break is due.", "break is due", "break not due yet"),
]


def test_every_question_validates_against_decider_schema():
    qs = build_questions(RULES)
    assert set(qs) == {"rule_1", "rule_2", "interrupt_ok"}
    req = SystemOneRequest(state="Measured now: nothing.", questions=qs)
    assert all(q.type == "noul" for q in req.questions.values())


def test_rule_question_shape():
    q = rule_question(RULES[0])
    assert q["instructions"].startswith("Does rule 1 apply right now? Rule 1: ")
    assert q["criteria"] == {"true": RULES[0].when_true, "false": RULES[0].when_false}


def test_interrupt_ok_is_the_v2_wording():
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "eval"))
    from s1_questions import V2

    assert INTERRUPT_OK == V2["interrupt_ok"]
    assert "interrupt_ok" not in build_questions(RULES, include_interrupt=False)
