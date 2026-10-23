from myrmidon.bus import EventBus
from myrmidon.contract import errors
from myrmidon.memory import PreferenceStore
from myrmidon.stats import StatsStore
from myrmidon.verify import Verifier, judge


class Tracker:
    def __init__(self, d=27.4, s=0.71):
        self.face, self.distance_cm, self.squint_ratio = True, d, s


class Clock:
    def __init__(self):
        self.t = 1_792_650_000.0

    def __call__(self):
        return self.t


def test_judge():
    assert judge({"distance_cm": 27.4, "squint": 0.71}, {"distance_cm": 41.2, "squint": 0.93}) == "worked"
    assert judge({"distance_cm": 50, "squint": 0.70}, {"distance_cm": 50, "squint": 0.82}) == "worked"
    assert judge({"distance_cm": 35, "squint": 0.80}, {"distance_cm": 31, "squint": 0.74}) == "worse"
    assert judge({"distance_cm": 35, "squint": 0.80}, {"distance_cm": 36, "squint": 0.82}) == "no_change"
    assert judge({"distance_cm": 35, "squint": 0.80}, {"distance_cm": None, "squint": None}) == "n/a"


def test_watch_emits_worked_after_window(runtime_dir):
    bus = EventBus(validate=True)
    seen = []
    bus.add_listener(seen.append)
    clock, tr = Clock(), Tracker()
    stats = StatsStore(runtime_dir / "p", clock)
    prefs = PreferenceStore(runtime_dir / "p" / "preferences.json")
    v = Verifier(bus, tr, stats, prefs, clock, window_s=30)
    v.watch("a_000057", "enlarge_text", v.measure(), "pdf")
    clock.t += 29
    v.on_time(clock.t)
    assert seen == []
    tr.distance_cm, tr.squint_ratio = 41.2, 0.93
    clock.t += 1
    v.on_time(clock.t)
    ev = seen[-1]
    assert ev["type"] == "verification" and errors(ev, "ServerEvent") == []
    assert ev["data"]["outcome"] == "worked"
    assert ev["data"]["before"] == {"distance_cm": 27.4, "squint": 0.71}
    assert ev["data"]["after"] == {"distance_cm": 41.2, "squint": 0.93}
    assert stats.get("adaptations_worked") == 1 and prefs.counts("enlarge_text", "pdf")["worked"] == 1


def test_no_face_gives_na_and_break_outcomes(runtime_dir):
    bus = EventBus(validate=True)
    seen = []
    bus.add_listener(seen.append)
    clock, tr = Clock(), Tracker()
    v = Verifier(bus, tr, StatsStore(runtime_dir / "p", clock),
                 PreferenceStore(runtime_dir / "p" / "preferences.json"), clock)
    v.watch("a_1", "dark_mode", v.measure(), "browser")
    tr.face = False
    clock.t += 31
    v.on_time(clock.t)
    assert seen[-1]["data"]["outcome"] == "n/a" and seen[-1]["data"]["after"] == {"distance_cm": None, "squint": None}
    v.on_break_outcome("a_2", "verified", {"distance_cm": 50, "squint": 0.9}, {"distance_cm": 52, "squint": 0.95}, 21.0)
    assert seen[-1]["data"]["outcome"] == "worked" and seen[-1]["data"]["window_s"] == 21.0
    assert all(errors(e, "ServerEvent") == [] for e in seen)
