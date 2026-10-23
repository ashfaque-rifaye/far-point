import json
import re

from myrmidon.config import DEFAULT_TRACE
from myrmidon.signals import SensorSample, SignalTracker
from myrmidon.sources import ROW_KEYS, ReplayClock, ReplaySource, TraceRecorder, load_trace


def test_replay_at_speed_100_gives_expected_tracker_states():
    tracker = SignalTracker()
    clock = ReplayClock(base=1_792_650_000.0)
    seen: dict[str, dict] = {}
    marks = {"lean_in": 20.0, "dark": 80.0, "teams": 120.0, "away": 185.0, "end": 239.0}

    def on_time(t):
        rel = t - clock.base
        for name, at in marks.items():
            if name not in seen and rel >= at:
                f = tracker.snapshot()
                seen[name] = {"distance": f.distance_cm, "under_near_s": f.under_near_s, "room": f.room,
                              "category": f.app_category, "bout_min": f.bout_min_now,
                              "looking": f.looking_at_screen, "activity": f.activity}

    src = ReplaySource(DEFAULT_TRACE, tracker, on_time, clock, speed=100)
    src.start()
    assert src.done.wait(30), "replay did not finish"
    assert src.rows_fed == len(src.rows) == 1200
    assert 26 <= seen["lean_in"]["distance"] <= 28 and seen["lean_in"]["under_near_s"] > 5
    assert seen["dark"]["room"] == "dark"
    assert seen["teams"]["category"] == "meeting" and seen["teams"]["activity"].startswith("in a video call")
    assert seen["teams"]["bout_min"] >= 45  # seeded 2595 s + ~2 min of near work
    assert seen["away"]["looking"] is False
    assert seen["end"]["looking"] is True and seen["end"]["category"] == "pdf"


def test_trace_is_numbers_only():
    raw = DEFAULT_TRACE.read_text(encoding="utf-8")
    header, rows = load_trace(DEFAULT_TRACE)
    assert header["kind"] == "header" and header["synthetic"] is True and header["seed_bout_s"] == 2595
    assert all(set(r) == set(ROW_KEYS) for r in rows)
    assert not re.search(r'"(image|images|frame|jpeg|png|b64)"', raw)
    assert "/9j/4" not in raw and "iVBORw0KGgo" not in raw and "data:image" not in raw


def test_trace_recorder_writes_numbers_only(runtime_dir):
    rec = TraceRecorder(runtime_dir, {"profile": "test"})
    rec.write(100.0, SensorSample(True, 51.234, 0.27, 0.97, 1.0, -2.0, 120.0),
              {"process": "msedge.exe", "idle_s": 3.0, "fullscreen": False}, "light", 60)
    rec.close()
    lines = rec.path.read_text().splitlines()
    assert json.loads(lines[0])["kind"] == "header"
    row = json.loads(lines[1])
    assert set(row) == set(ROW_KEYS) and row["title"] == "" and row["distance_cm"] == 51.23
    assert rec.path.parent.name == "recordings" and str(rec.path).startswith(str(runtime_dir))
