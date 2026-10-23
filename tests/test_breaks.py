from myrmidon.act import DryRunOverlay
from myrmidon.breaks import BreakManager
from myrmidon.bus import EventBus
from myrmidon.contract import errors
from myrmidon.stats import StatsStore


class Tracker:
    def __init__(self):
        self.face, self.distance_cm, self.squint_ratio = True, 55.0, 0.95
        self.looking_at_screen = True
        self.resets = 0

    def reset_bout(self):
        self.resets += 1


class Clock:
    def __init__(self, t=1_792_650_000.0):
        self.t = t

    def __call__(self):
        return self.t


def setup(runtime_dir):
    bus = EventBus(validate=True)
    seen = []
    bus.add_listener(seen.append)
    clock, tr, ov = Clock(), Tracker(), DryRunOverlay()
    outcomes = []
    bm = BreakManager(bus, ov, tr, StatsStore(runtime_dir / "p", clock), clock,
                      on_outcome=lambda **kw: outcomes.append(kw))
    return bm, bus, seen, clock, tr, ov, outcomes


def run(bm, clock, seconds, step=0.1):
    for _ in range(int(seconds / step)):
        clock.t += step
        bm.on_time(clock.t)


def phases(seen):
    return [e["data"]["phase"] for e in seen if e["type"] == "break"]


def test_twenty_seconds_away_verifies_and_resets_bout(runtime_dir):
    bm, bus, seen, clock, tr, ov, outcomes = setup(runtime_dir)
    bid = bm.start(20, action_id="a_000001")
    assert bid.startswith("b_") and ov.calls[0] == ("break", 20)
    tr.looking_at_screen = False
    run(bm, clock, 21)
    p = phases(seen)
    assert p[:2] == ["offered", "started"] and p[-1] == "verified" and "tick" in p
    assert tr.resets == 1 and bm.streak == 1 and not bm.is_active()
    assert outcomes[0]["phase"] == "verified" and outcomes[0]["action_id"] == "a_000001"
    assert all(errors(e, "ServerEvent") == [] for e in seen)


def test_face_absent_counts_and_is_noted(runtime_dir):
    bm, bus, seen, clock, tr, ov, _ = setup(runtime_dir)
    bm.start(20)
    tr.looking_at_screen = None  # walked away
    run(bm, clock, 21)
    last = [e for e in seen if e["type"] == "break"][-1]["data"]
    assert last["phase"] == "verified" and last["face_absent_s"] >= 19


def test_looking_back_for_60s_is_abandoned(runtime_dir):
    bm, bus, seen, clock, tr, ov, outcomes = setup(runtime_dir)
    bm.start(20)
    tr.looking_at_screen = True
    run(bm, clock, 61)
    assert phases(seen)[-1] == "abandoned" and bm.streak == 0 and tr.resets == 0


def test_skip(runtime_dir):
    bm, bus, seen, clock, tr, ov, outcomes = setup(runtime_dir)
    bid = bm.start(20)
    assert bm.skip("b_nope") is False
    ov.on_skip()  # Esc in the overlay
    assert phases(seen)[-1] == "skipped" and not bm.is_active() and ("close",) in ov.calls
    assert bm.skip(bid) is False
