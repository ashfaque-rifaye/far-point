from farpoint.memory import MomentLog, PreferenceStore


def test_demotion_after_three_failures(runtime_dir):
    p = PreferenceStore(runtime_dir / "prefs.json")
    for _ in range(2):
        p.record("enlarge_text", "pdf", "no_change")
    assert not p.demoted("enlarge_text", "pdf")
    p.record("enlarge_text", "pdf", "worse")
    assert p.demoted("enlarge_text", "pdf")
    assert not p.demoted("enlarge_text", "browser")
    p.record("enlarge_text", "pdf", "worked")
    p.record("enlarge_text", "pdf", "worked")
    assert not p.demoted("enlarge_text", "pdf")  # 2/5 = 40% worked
    p.record("dark_mode", "pdf", "n/a")
    assert p.counts("dark_mode", "pdf")["n/a"] == 1 and not p.demoted("dark_mode", "pdf")
    assert PreferenceStore(runtime_dir / "prefs.json").demoted("enlarge_text", "pdf") is False  # persisted


def test_moment_log_roundtrip(runtime_dir):
    log = MomentLog(runtime_dir / "moments.jsonl", clock=lambda: 1_792_650_000.0)
    a = log.log("unsure", "rule 3 unsure, escalation off", p=0.52)
    b = log.log("escalated", "rule 1 escalated", p=0.44, nova=True, latency_ms=820)
    assert [m["id"] for m in log.unreviewed()] == [a["id"], b["id"]]
    log.mark_reviewed([a["id"]])
    again = MomentLog(runtime_dir / "moments.jsonl")
    assert [m["id"] for m in again.unreviewed()] == [b["id"]]
    assert again.get([a["id"]])[0]["data"] == {"p": 0.52}
    c = again.log("ask", "asked")
    assert c["id"] == "m_000003"
