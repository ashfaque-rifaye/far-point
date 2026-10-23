"""End to end: the FastAPI app in REPLAY mode over the demo trace, read through the WebSocket.

No GPU, no AWS, no camera: FAKE oracle Decider, Bedrock off, dry-run actuators.
"""
from fastapi.testclient import TestClient

from myrmidon.config import DEFAULT_TRACE, Settings
from myrmidon.contract import errors
from myrmidon.dashboard import create_app
from myrmidon.runtime import Runtime

WS = "ws://127.0.0.1:8765/ws"
BASE = "http://127.0.0.1:8765"


def collect_until_replay_done(ws, limit=5000):
    frames = []
    for _ in range(limit):
        m = ws.receive_json()
        frames.append(m)
        if m["type"] == "toast" and m["data"]["text"].startswith("Replay finished"):
            return frames
    raise AssertionError("replay did not finish")


def of(frames, kind):
    return [f["data"] for f in frames if f["type"] == kind]


def test_replay_end_to_end_over_websocket(tmp_path):
    s = Settings(mode="replay", trace=DEFAULT_TRACE, runtime_dir=tmp_path, fake_decider=True, no_bedrock=True,
                 speed=50, record=True, web_dist=tmp_path / "no-dist")
    rt = Runtime(s, bedrock_available=False)
    app = create_app(rt)
    with TestClient(app, base_url=BASE) as client:
        with client.websocket_connect(WS, headers={"origin": BASE}) as ws:
            frames = collect_until_replay_done(ws)
    bad = [(f["type"], errors(f, "ServerEvent")) for f in frames if errors(f, "ServerEvent")]
    assert bad == []
    assert frames[0]["type"] == "hello" and frames[0]["data"]["mode"] == "replay"

    decisions, actions = of(frames, "decision"), of(frames, "action")
    verifications = {v["action_id"]: v for v in of(frames, "verification")}
    by_tool = {}
    for a in actions:
        by_tool.setdefault(a["tool"], []).append(a)

    # decision(act, enlarge_text) -> action(done) -> verification(worked)
    enlarge = by_tool["enlarge_text"][0]
    d = next(x for x in decisions if x["id"] == enlarge["decision_id"])
    assert d["policy"] == "act" and d["answers"]["next_action"]["choice"] == "enlarge_text"
    assert enlarge["status"] == "done" and verifications[enlarge["id"]]["outcome"] == "worked"
    order = [f["type"] for f in frames]
    i_dec = next(i for i, f in enumerate(frames) if f["type"] == "decision" and f["data"]["id"] == d["id"])
    i_act = next(i for i, f in enumerate(frames) if f["type"] == "action" and f["data"]["id"] == enlarge["id"])
    i_ver = next(i for i, f in enumerate(frames) if f["type"] == "verification" and f["data"]["action_id"] == enlarge["id"])
    assert i_dec < i_act < i_ver, order

    # dark mode acted
    assert by_tool["dark_mode"][0]["status"] == "done"

    # InterruptGate denied the break during the Teams call, then it proceeded and was verified
    breaks = by_tool["far_look_break"]
    denied = [a for a in breaks if a["status"] == "denied"]
    assert denied and denied[0]["gate"]["name"] == "InterruptGate" and denied[0]["gate"]["verdict"] == "deny"
    assert any("in a video call" in x["state_text"] for x in decisions if x["id"] == denied[0]["decision_id"])
    phases = [b["phase"] for b in of(frames, "break")]
    assert phases[0] == "offered" and phases[1] == "started" and phases[-1] == "verified"
    done_break = [a for a in breaks if a["status"] == "done"][0]
    assert verifications[done_break["id"]]["outcome"] == "worked"

    stats = of(frames, "stats")[-1]
    assert stats["face_images_uploaded"] == 0 and stats["breaks_verified"] == 1 and stats["adaptations_worked"] >= 3

    # after shutdown the dry-run actuators report everything restored
    assert rt.stopped and rt.restored == {"zoom": True, "brightness": True, "theme": True}
    assert rt.actuators.journal.entries() == {}
    assert rt.actuators.state()["zoom_step"] == 0 and rt.actuators.state()["theme"] == "light"

    # the recorded bus trace replays through --events
    recordings = sorted((tmp_path / "recordings").glob("events-*.jsonl"))
    assert recordings, "EventRecorder wrote nothing"
    s2 = Settings(mode="replay", events=recordings[-1], runtime_dir=tmp_path / "ev", fake_decider=True,
                  no_bedrock=True, speed=50, web_dist=tmp_path / "no-dist")
    rt2 = Runtime(s2, bedrock_available=False)
    with TestClient(create_app(rt2), base_url=BASE) as client:
        with client.websocket_connect(WS) as ws:
            frames2 = collect_until_replay_done(ws)
    replayed_ids = {f["data"]["id"] for f in frames2 if f["type"] == "action"}
    assert {a["id"] for a in actions} <= replayed_ids
    assert all(errors(f, "ServerEvent") == [] for f in frames2)
