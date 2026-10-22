from patterns.reflex_gate.examples import posture_agent


def test_posture_example_offline(capsys):
    rows = posture_agent.main(["--fake"])
    out = capsys.readouterr().out
    assert out.count("state ") == 4
    by_state = {r["state"]: r for r in rows}
    assert by_state["fresh start"]["policy"] == "quiet"
    assert by_state["slouching"]["tool"] == "posture_nudge"
    assert by_state["slouching"]["result"] == "success"
    assert by_state["long sit"]["tool"] == "stand_break"
    meeting = by_state["slouching in a meeting"]
    assert meeting["tool"] == "posture_nudge"
    assert meeting["gate"]["verdict"] == "deny" and meeting["result"] == "denied"
