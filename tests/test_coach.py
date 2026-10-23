import time

import pytest

from farpoint.bus import EventBus
from farpoint.coach import DISCLAIMER, Coach, red_flags
from farpoint.confirm import ConfirmBroker
from farpoint.contract import errors
from farpoint.doctrine import DoctrineStore
from farpoint.memory import MomentLog
from farpoint.stats import StatsStore
from patterns.reflex_gate import ScriptedModel, contains_image

RULE = {"n": 1, "text": "The Viewing distance line says enlarging needed.", "tool": "enlarge_text",
        "args": {"steps": 1}, "when_true": "the Viewing distance line says 'enlarging needed'",
        "when_false": "the Viewing distance line says 'no enlarging needed'",
        "basis": "Your description: 'myopia -3.5'"}
DOCTRINE_INPUT = {
    "profile": {"glasses_for_screen": "yes", "conditions": ["myopia -3.5 both eyes", "glare at night"]},
    "limits": {"near_cm": 35, "bout_min": 30},
    "rules": [RULE, {**RULE, "n": 2, "tool": "dark_mode", "text": "The Theme line says dark mode needed.",
                     "when_true": "the Theme line says 'mismatch, dark mode needed'",
                     "when_false": "the Theme line says 'no change needed'", "basis": "Your description: 'glare at night'"}],
}


class Clock:
    def __init__(self):
        self.t = 1_792_650_000.0

    def __call__(self):
        return self.t


def make(runtime_dir, script, deny_without_client=True):
    bus = EventBus(validate=True)
    seen = []
    bus.add_listener(seen.append)
    clock = Clock()
    store = DoctrineStore(runtime_dir / "profile")
    stats = StatsStore(runtime_dir / "profile", clock)
    moments = MomentLog(runtime_dir / "profile" / "moments.jsonl", clock)
    broker = ConfirmBroker(bus, deny_without_client=deny_without_client)
    model = ScriptedModel(script=script)
    opened = []
    coach = Coach(bus, store, stats, moments, broker, model_factory=lambda: model, startfile=opened.append,
                  clock=clock)
    return coach, model, seen, store, broker, opened, moments


def kinds(seen, kind):
    return [e["data"] for e in seen if e["type"] == kind]


def test_compile_doctrine_gives_unapproved_v2(runtime_dir):
    coach, model, seen, store, *_ = make(runtime_dir, [{"tool": "write_doctrine", "input": DOCTRINE_INPUT},
                                                       {"text": "Done."}])
    assert coach.compile_doctrine("Myopia -3.5 both eyes, glasses for screen work, glare bothers me at night") == 2
    d = kinds(seen, "doctrine")[-1]
    assert d["version"] == 2 and d["approved"] is False and [r["origin"] for r in d["rules"]] == ["bedrock"] * 2
    assert store.active.version == 1 and store.current_draft.limits.near_cm == 35
    assert store.current_draft.profile.glasses_for_screen == "yes"
    assert all(errors(e, "ServerEvent") == [] for e in seen)
    assert not contains_image(model.calls)
    assert "Behavioral observations, not a diagnosis" in model.calls[0]["system_prompt"]
    assert coach.stats.get("bedrock_tokens") > 0


def test_second_write_doctrine_in_one_compile_saves_nothing_new(runtime_dir):
    coach, model, seen, store, *_ = make(runtime_dir, [{"tool": "write_doctrine", "input": DOCTRINE_INPUT},
                                                       {"tool": "write_doctrine", "input": DOCTRINE_INPUT},
                                                       {"text": "Done."}])
    assert coach.compile_doctrine("myopia") == 2
    assert store.current_draft.version == 2 and len(kinds(seen, "doctrine")) == 1


def test_invalid_tool_is_retried_then_saved(runtime_dir):
    bad = {**DOCTRINE_INPUT, "rules": [{**RULE, "tool": "format_disk"}]}
    coach, model, seen, store, *_ = make(runtime_dir, [{"tool": "write_doctrine", "input": bad},
                                                       {"tool": "write_doctrine", "input": DOCTRINE_INPUT},
                                                       {"text": "Fixed."}])
    assert coach.compile_doctrine("myopia") == 2
    tool_results = [b["toolResult"] for c in model.calls for m in c["messages"] for b in m["content"]
                    if "toolResult" in b]
    assert tool_results[0]["status"] == "error" and "Invalid rulebook" in tool_results[0]["content"][0]["text"]


def test_three_invalid_attempts_keep_current_rules(runtime_dir):
    bad = {**DOCTRINE_INPUT, "rules": [{**RULE, "tool": "format_disk"}]}
    script = [{"tool": "write_doctrine", "input": bad}] * 4 + [{"text": "Sorry."}]
    coach, model, seen, store, *_ = make(runtime_dir, script)
    assert coach.compile_doctrine("myopia") is None
    assert store.current_draft.version == 1
    assert any("Could not build" in t["text"] for t in kinds(seen, "toast"))


def test_tidy_rules_dedupes_and_keeps_ask_user_last():
    from farpoint.coach import tidy_rules
    from farpoint.doctrine import DoctrineRule
    ask = DoctrineRule(**{**RULE, "n": 1, "tool": "ask_user", "when_true": "the Squint despite zoom line ends with 'yes'"})
    a = DoctrineRule(**{**RULE, "n": 2})
    dup = DoctrineRule(**{**RULE, "n": 3, "text": "Same condition, other words."})
    out = tidy_rules([ask, a, dup])
    assert [(r.n, r.tool) for r in out] == [(1, "enlarge_text"), (2, "ask_user")]


def test_red_flags_warn(runtime_dir):
    coach, model, seen, *_ = make(runtime_dir, [{"tool": "write_doctrine", "input": DOCTRINE_INPUT}, {"text": "ok"}])
    coach.compile_doctrine("I see sudden flashes and a curtain over my left eye")
    toast = kinds(seen, "toast")[0]
    assert toast["level"] == "warning" and "eye doctor" in toast["text"]
    assert set(red_flags("double vision and eye pain")) >= {"double vision", "eye pain"}


def test_adopt_needs_token_or_approval(runtime_dir):
    coach, model, seen, store, broker, *_ = make(runtime_dir, [{"tool": "write_doctrine", "input": DOCTRINE_INPUT},
                                                               {"text": "Done."}])
    coach.compile_doctrine("myopia")
    res = coach.direct.tool.adopt_doctrine(version=2)  # no token, no UI connected -> deny
    assert res["status"] == "error" and res["content"][0]["text"].startswith("CONFIRMATION_FAILED:")
    assert store.active.version == 1
    assert coach.adopt(2) is True  # the UI command path: single-use token
    assert store.active.version == 2 and kinds(seen, "doctrine")[-1]["approved"] is True
    assert coach.adopt(1) is False  # stale
    assert any("out of date" in t["text"] for t in kinds(seen, "toast"))
    assert model.calls and all("adopt_doctrine" not in str(c["messages"]) for c in model.calls)


def test_report_starts_with_disclaimer(runtime_dir):
    coach, model, seen, *_ = make(runtime_dir, [{"tool": "get_today_stats", "input": {}},
                                                {"text": "## Today\n\n- 12 min closer than 30 cm <b>x</b>"}])
    coach.stats.inc("breaks_verified", 2)
    r = coach.report("today")
    assert r["markdown"].startswith(DISCLAIMER) and "<b>" not in r["markdown"]
    assert kinds(seen, "report")[-1]["id"] == r["id"] and errors({"v": 1, "type": "report", "t": 1, "data": r},
                                                                  "ServerEvent") == []
    tool_results = [b["toolResult"] for c in model.calls for m in c["messages"] for b in m["content"]
                    if "toolResult" in b]
    assert '"breaks_verified": 2' in str(tool_results[0]["content"]) or "breaks_verified" in str(tool_results[0])


def test_propose_rule_then_approve_adds_rule(runtime_dir):
    coach, model, seen, store, broker, opened, moments = make(runtime_dir, [
        {"tool": "propose_rule", "input": {"rule_text": "When reading PDFs after 21:00, enlarge text.",
                                           "tool": "enlarge_text",
                                           "when_true": "the Text zoom line says (pdf) and it is after 21:00",
                                           "when_false": "otherwise", "reason": "Three late PDF sessions",
                                           "moment_ids": ["m_000001", "m_000002"]}},
        {"text": "Proposed."}])
    for i in range(3):
        moments.log("unsure", f"late pdf squint {i}", p=0.5)
    assert coach.review_moments() == 1
    p = kinds(seen, "proposal")[-1]
    assert p["status"] == "pending" and len(p["moments"]) == 2
    assert moments.unreviewed() == []
    assert coach.approve_proposal(p["id"]) is True
    assert kinds(seen, "proposal")[-1]["status"] == "approved"
    d = kinds(seen, "doctrine")[-1]
    assert d["version"] == 2 and any(r["origin"] == "proposal" for r in d["rules"])
    assert d["rules"][-1]["text"].startswith("The Squint despite zoom")  # ask_user stays last
    assert coach.reject_proposal(p["id"]) is False


def test_exam_email_deny_never_opens_and_approve_opens_mailto(runtime_dir):
    script = [{"tool": "summarize_period", "input": {"days": 14}},
              {"tool": "draft_exam_request", "input": {"subject": "Eye exam request",
                                                        "body": "Hello, I would like to book an eye exam."}},
              {"text": "Drafted."}]
    coach, model, seen, store, broker, opened, _ = make(runtime_dir, list(script), deny_without_client=False)
    eid = coach.draft_exam()
    statuses = [e["status"] for e in kinds(seen, "email_draft")]
    assert statuses == ["draft", "pending_confirm"]
    rid = kinds(seen, "confirm_request")[-1]["request_id"]
    broker.resolve(rid, False)
    assert kinds(seen, "email_draft")[-1]["status"] == "draft" and opened == []
    # second draft, approved
    model.script.extend(script)
    eid2 = coach.draft_exam()
    rid2 = kinds(seen, "confirm_request")[-1]["request_id"]
    broker.resolve(rid2, True)
    for _ in range(100):
        if opened:
            break
        time.sleep(0.02)
    assert len(opened) == 1 and opened[0].startswith("mailto:?subject=Eye%20exam%20request")
    assert kinds(seen, "email_draft")[-1] == {**kinds(seen, "email_draft")[-1], "id": eid2, "status": "opened"}
    assert eid != eid2 and not contains_image(model.calls)


def test_coach_off_without_bedrock(runtime_dir):
    coach, model, seen, *_ = make(runtime_dir, [])
    coach.enabled = False
    assert coach.report("today") is None and coach.compile_doctrine("myopia") is None
    assert all("Coach not available" in t["text"] for t in kinds(seen, "toast"))
    assert model.attempts == 0


@pytest.mark.live
def test_live_compile_doctrine_with_nova_lite(runtime_dir):
    bus = EventBus(validate=True)
    seen = []
    bus.add_listener(seen.append)
    store = DoctrineStore(runtime_dir / "profile")
    stats = StatsStore(runtime_dir / "profile")
    coach = Coach(bus, store, stats, MomentLog(runtime_dir / "m.jsonl"), ConfirmBroker(bus))
    v = coach.compile_doctrine("Myopia -3.5 both eyes, glasses for screen work, glare bothers me at night")
    d = store.current_draft
    print(f"\nversion={v} approved={d.approved} glasses={d.profile.glasses_for_screen} limits={d.limits.model_dump()}")
    for r in d.rules:
        print(f"  {r.n}. [{r.tool}] {r.text} | basis: {r.basis}")
    print("bedrock calls/tokens:", stats.get("bedrock_calls"), stats.get("bedrock_tokens"))
    assert v == 2 and not d.approved and len(d.rules) >= 3
    assert all(errors(e, "ServerEvent") == [] for e in seen)


def test_report_preamble_is_stripped():
    from farpoint.coach import strip_preamble
    md = "I have the data from the tools. I will now format it.\n\n- Today, 0.3 min closer than 30 cm."
    assert strip_preamble(md) == "- Today, 0.3 min closer than 30 cm."
    assert strip_preamble("## Today\n- Here is a line") == "## Today\n- Here is a line"


def test_report_tool_narration_is_dropped():
    from farpoint.coach import strip_preamble
    md = ("The rule proposal has been sent for human approval. I will now inform the user about the report.\n"
          "Here is your short report for today:\n- **Breaks verified:** 4\n"
          "I have also proposed a rule for you to consider: a break every 45 minutes.")
    assert strip_preamble(md) == "- **Breaks verified:** 4"
    assert strip_preamble("- I will keep my distance tip short") == "- I will keep my distance tip short"
