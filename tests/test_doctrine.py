import pytest
from pydantic import ValidationError

from myrmidon.contract import errors
from myrmidon.doctrine import (
    TOOLS,
    DoctrineRule,
    DoctrineStore,
    Limits,
    Profile,
    StaleVersion,
    default_doctrine,
)


def rule(n=1, tool="enlarge_text", **kw):
    base = dict(n=n, text="A rule text.", tool=tool, when_true="yes it holds", when_false="no it does not")
    base.update(kw)
    return DoctrineRule(**base)


def test_unknown_tool_is_rejected():
    with pytest.raises(ValidationError):
        rule(tool="format_disk")
    assert set(TOOLS) >= {"enlarge_text", "ask_user", "reset"}


def test_limits_are_clamped():
    L = Limits(near_cm=5, near_s=1000, bout_min=45, squint_ratio=2)
    assert (L.near_cm, L.near_s, L.bout_min, L.squint_ratio) == (20, 60, 45, 0.95)


def test_default_doctrine_matches_contract_and_plan():
    d = default_doctrine()
    assert d.version == 1 and d.approved
    assert [r.tool for r in d.active_rules()] == [
        "enlarge_text", "glasses_reminder", "dark_mode", "dim_screen", "brighten_screen",
        "far_look_break", "reduce_text", "ask_user",
    ]
    assert errors(d.to_contract(), "DoctrineData") == []
    assert d.limits.near_cm == 30 and d.limits.near_s == 5 and d.limits.bout_cm == 60 and d.limits.bout_min == 45
    pr = d.to_pattern_rules()
    assert [r.n for r in pr] == list(range(1, 9)) and pr[0].tool == "enlarge_text"


def test_store_draft_approve_and_stale(runtime_dir):
    store = DoctrineStore(runtime_dir / "profile")
    assert store.active.version == 1
    draft = store.save_draft("Myopia -3.5", Profile(glasses_for_screen="yes"), Limits(near_cm=35),
                             [rule(2, "dark_mode", origin="bedrock"), rule(1, origin="bedrock")])
    assert draft.version == 2 and not draft.approved
    assert [r.n for r in draft.rules] == [1, 2] and draft.rules[0].tool == "enlarge_text"
    assert store.current_draft.version == 2 and store.active.version == 1
    with pytest.raises(StaleVersion):
        store.approve(7)
    approved = store.approve(2)
    assert approved.approved and store.active.version == 2 and store.active.profile.glasses_for_screen == "yes"
    assert store.approve(2).version == 2  # idempotent for the active version
    # persisted
    again = DoctrineStore(runtime_dir / "profile")
    assert again.active.version == 2 and again.active.limits.near_cm == 35
    # a newer draft makes the active version stale for approval
    again.save_draft("v3", Profile(), Limits(), [rule(1)])
    with pytest.raises(StaleVersion):
        again.approve(2)
    assert again.approve(3).version == 3


def test_update_profile_keeps_rules_and_pending_draft_approvable(runtime_dir):
    store = DoctrineStore(runtime_dir / "profile")
    draft = store.save_draft("myopia", Profile(), Limits(), [rule(1)])
    d = store.update_profile(glasses_for_screen="yes")
    assert d.approved and d.profile.glasses_for_screen == "yes" and len(d.rules) == 8
    assert store.current_draft.version > d.version > draft.version
    assert store.current_draft.profile.glasses_for_screen == "yes"
    assert store.approve(store.current_draft.version).profile.glasses_for_screen == "yes"
    with pytest.raises(ValueError):
        store.update_profile(glasses_for_screen="maybe")


def test_add_rule_goes_above_ask_user(runtime_dir):
    store = DoctrineStore(runtime_dir / "profile")
    d = store.add_rule(rule(99, "enlarge_text", origin="proposal", text="When reading PDFs after 21:00, enlarge."))
    assert d.version == 2 and d.approved
    tools = [r.tool for r in d.active_rules()]
    assert tools[-1] == "ask_user" and tools[-2] == "enlarge_text"
    assert d.active_rules()[-2].origin == "proposal"
    assert [r.n for r in d.active_rules()] == list(range(1, 10))
    with pytest.raises(StaleVersion):
        store.approve(1)
