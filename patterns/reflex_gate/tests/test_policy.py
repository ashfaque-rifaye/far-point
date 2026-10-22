import pytest

from patterns.reflex_gate import Rule, Thresholds, select

RULES = [
    Rule(1, "enlarge_text", "too close", "t", "f"),
    Rule(2, "glasses_reminder", "glasses off", "t", "f"),
    Rule(3, "dark_mode", "dark room, light theme", "t", "f"),
    Rule(8, "ask_user", "still squinting", "t", "f"),
]


def answers(**ps):
    out = {f"rule_{k.split('_')[1]}": {"type": "noul", "noul": v} for k, v in ps.items() if k.startswith("r_")}
    out["interrupt_ok"] = {"type": "noul", "noul": ps.get("io", 0.8)}
    return out


def test_fires():
    s = select(RULES, answers(r_1=0.9, r_2=0.1, r_3=0.1, r_8=0.1))
    assert (s.tool, s.rule_n, s.policy) == ("enlarge_text", 1, "act")
    assert s.next_action["choice"] == "enlarge_text"
    assert s.interrupt_p == pytest.approx(0.8)


def test_all_clear_is_quiet():
    s = select(RULES, answers(r_1=0.1, r_2=0.2, r_3=0.05, r_8=0.1))
    assert (s.tool, s.policy) == (None, "quiet")
    assert s.next_action["choice"] == "none"
    assert s.reason == "no rule applies"


def test_unsure_above_firing_rule_escalates():
    seen = []

    def esc(rules):
        seen.append([r.n for r in rules])
        return {1: True}

    s = select(RULES, answers(r_1=0.5, r_2=0.1, r_3=0.9, r_8=0.1), escalate=esc)
    assert seen == [[1]]
    assert (s.tool, s.policy) == ("enlarge_text", "act")
    assert s.verdicts[0].escalated is True
    assert s.escalation["rules"] == [1]


def test_escalation_false_falls_through_to_lower_rule():
    s = select(RULES, answers(r_1=0.5, r_2=0.1, r_3=0.9, r_8=0.1), escalate=lambda rules: {1: False})
    assert (s.tool, s.rule_n) == ("dark_mode", 3)


def test_escalation_none_or_unavailable_fails_quiet():
    a = answers(r_1=0.5, r_2=0.1, r_3=0.9, r_8=0.1)
    s = select(RULES, a, escalate=lambda rules: {1: None})
    assert (s.tool, s.policy) == (None, "quiet")
    assert "fail quiet" in s.reason
    s2 = select(RULES, a, escalate=None)
    assert (s2.tool, s2.policy, s2.unsure) == (None, "quiet", [1])
    assert "escalation unavailable" in s2.reason


def test_escalation_error_fails_quiet():
    def boom(rules):
        raise TimeoutError("slow")

    s = select(RULES, answers(r_1=0.5, r_2=0.1, r_3=0.9), escalate=boom)
    assert s.policy == "quiet"
    assert s.escalation["error"] == "TimeoutError"


def test_unsure_below_firing_rule_is_not_escalated():
    called = []
    s = select(RULES, answers(r_1=0.9, r_2=0.5, r_3=0.5), escalate=lambda r: called.append(r) or {})
    assert s.tool == "enlarge_text" and called == []


def test_priority_order_wins_over_higher_probability():
    s = select(RULES, answers(r_1=0.7, r_2=0.99, r_3=0.95, r_8=0.1))
    assert s.tool == "enlarge_text"


def test_ask_policy_and_cooldown():
    a = answers(r_1=0.1, r_2=0.1, r_3=0.1, r_8=0.9)
    s = select(RULES, a, now=10_000.0, last_ask_t=None)
    assert (s.tool, s.policy) == ("ask_user", "ask")
    s2 = select(RULES, a, now=10_000.0, last_ask_t=10_000.0 - 600)
    assert (s2.tool, s2.policy) == (None, "quiet")
    s3 = select(RULES, a, now=10_000.0, last_ask_t=10_000.0 - 1800)
    assert s3.tool == "ask_user"


def test_probs_sum_to_one_and_thresholds_are_configurable():
    s = select(RULES, answers(r_1=0.6, r_2=0.3, r_3=0.2, r_8=0.1), thresholds=Thresholds(fire_p=0.55))
    assert s.tool == "enlarge_text"
    assert sum(s.next_action["probs"].values()) == pytest.approx(1.0, abs=1e-3)
    assert set(s.next_action["probs"]) == {"enlarge_text", "glasses_reminder", "dark_mode", "ask_user", "none"}
    assert 0 <= s.next_action["confidence"] <= 1
