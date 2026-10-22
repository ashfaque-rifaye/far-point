import asyncio
import json

from farpoint.bus import EventBus, EventRecorder
from farpoint.contract import errors
from farpoint.doctrine import default_doctrine

HELLO = {
    "mode": "replay", "app_version": "0.2.0", "profile_name": "you",
    "decider": {"status": "ready", "model": "FAKE oracle (tests/demo)", "device": "cpu", "vision": False},
    "bedrock": {"status": "off", "model": None}, "camera": {"status": "off"},
}
STATS = {"day": "2026-10-22", "under30_min": 0, "longest_bout_min": 0, "breaks_offered": 0, "breaks_verified": 0,
         "streak": 0, "squint_episodes": 0, "glasses_off_min": 0, "adaptations": 0, "adaptations_worked": 0,
         "decisions": 0, "decider_p50_ms": 0, "decider_p95_ms": 0, "face_images_uploaded": 0,
         "bedrock_calls": 0, "bedrock_tokens": 0}


def proposal(pid, status):
    return {"id": pid, "rule_text": "r", "reason": "x", "moments": [{"t": 1, "note": "n"}], "status": status}


def test_connect_burst_order_and_validation(tmp_path):
    rec = EventRecorder(tmp_path / "events.jsonl")
    bus = EventBus(recorder=rec, validate=True)
    seen = []
    bus.add_listener(seen.append)
    bus.publish("stats", STATS)
    bus.publish("proposal", proposal("p_1", "pending"))
    bus.publish("proposal", proposal("p_2", "pending"))
    bus.publish("proposal", proposal("p_2", "rejected"))
    bus.publish("doctrine", default_doctrine().to_contract())
    bus.publish("hello", HELLO)
    burst = bus.connect_burst()
    assert [e["type"] for e in burst] == ["hello", "doctrine", "proposal", "stats"]
    assert burst[2]["data"]["id"] == "p_1"
    for env in seen + burst:
        assert errors(env, "ServerEvent") == [], env
    rec.close()
    lines = (tmp_path / "events.jsonl").read_text().splitlines()
    assert len(lines) == 6 and json.loads(lines[0])["type"] == "stats"


def test_signals_throttled_and_fanout_to_asyncio_queue():
    bus = EventBus()

    async def main():
        q = bus.subscribe(asyncio.get_running_loop())
        sig = {"face": False}
        sent = [bus.publish("signals", sig) for _ in range(20)]
        assert sum(1 for s in sent if s is not None) == 1  # 20 back-to-back -> 1 (<= 10 Hz)
        bus.toast("info", "hello")
        await asyncio.sleep(0.01)
        got = [q.get_nowait()["type"] for _ in range(q.qsize())]
        assert got == ["signals", "toast"]
        assert bus.unsubscribe(q) == 0

    asyncio.run(main())
