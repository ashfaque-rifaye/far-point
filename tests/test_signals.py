import pytest

from farpoint.contract import errors
from farpoint.doctrine import Limits
from farpoint.facts import too_close
from farpoint.sense import head_angles
from farpoint.signals import SensorSample, SignalTracker, ambient_bucket, distance_band

T0 = 1_800_000_000.0
HZ = 10


def feed(tr: SignalTracker, t: float, seconds: float, **kw) -> float:
    """Feed `seconds` of samples at 10 Hz starting at t; returns the end time."""
    n = int(round(seconds * HZ))
    face = kw.pop("face", True)
    sample = dict(distance_cm=55.0, ear=0.28, squint_ratio=1.0, yaw_deg=0.0, pitch_deg=0.0, luma=120.0)
    sample.update(kw)
    for i in range(n):
        tr.update(t + i / HZ, SensorSample(face=face, **sample) if face else SensorSample(face=False, luma=sample["luma"]))
    return t + n / HZ


def test_too_close_needs_more_than_near_s():
    L = Limits()
    tr = SignalTracker(L)
    t = feed(tr, T0, 2, distance_cm=55)
    feed(tr, t, 4.05, distance_cm=27)
    assert not too_close(tr.snapshot(), L)
    tr2 = SignalTracker(L)
    t = feed(tr2, T0, 2, distance_cm=55)
    feed(tr2, t, 6, distance_cm=27)
    f = tr2.snapshot()
    assert too_close(f, L) and f.distance_cm == 27 and f.under_near_s > 5


def test_bout_grows_and_resets_after_20s_far():
    tr = SignalTracker(Limits())
    tr.seed_bout(2640)
    t = feed(tr, T0, 30, distance_cm=50)
    assert tr.snapshot().bout_min_now == pytest.approx(44.5, abs=0.05)
    t = feed(tr, t, 10, distance_cm=80)
    assert tr.bout_s > 2600  # 10 s away: not reset yet
    t = feed(tr, t, 11, distance_cm=80)
    assert tr.bout_s == 0
    assert tr.longest_bout_s >= 2669


def test_twelve_blinks_in_60s_give_12_per_min():
    tr = SignalTracker(Limits())
    t = T0
    for _ in range(12):
        t = feed(tr, t, 4.8, squint_ratio=1.0)
        t = feed(tr, t, 0.2, squint_ratio=0.3)  # 2 frames closed
    t = feed(tr, t, 0.1, squint_ratio=1.0)
    assert tr.blink_per_min == pytest.approx(12, abs=0.6)
    assert tr.squinting is False  # median filter: blinks are not squints


def test_squint_debounce():
    L = Limits(squint_s=3)
    tr = SignalTracker(L)
    t = feed(tr, T0, 2, squint_ratio=1.0)
    t = feed(tr, t, 2.5, squint_ratio=0.6)
    assert not tr.squinting
    t = feed(tr, t, 1.5, squint_ratio=0.6)
    assert tr.squinting and tr.squinting_s >= 3 and tr.squint_episodes == 1
    feed(tr, t, 1, squint_ratio=0.95)
    assert not tr.squinting and tr.squinting_s == 0


def test_glasses_off_signs_need_lean_in_and_squint():
    tr = SignalTracker(Limits(lean_in_cm=8))
    t = feed(tr, T0, 40, distance_cm=55)
    assert tr.usual_distance_cm == pytest.approx(55)
    t = feed(tr, t, 5, distance_cm=44, squint_ratio=1.0)
    assert not tr.snapshot().glasses_off_signs
    feed(tr, t, 5, distance_cm=44, squint_ratio=0.6)
    assert tr.snapshot().glasses_off_signs


def test_looking_away_ambient_and_payload_schema():
    tr = SignalTracker(Limits())
    t = feed(tr, T0, 3, yaw_deg=40.0, luma=30.0)
    tr.update(t, SensorSample(face=True, distance_cm=52, ear=0.28, squint_ratio=0.98, yaw_deg=40, pitch_deg=0, luma=30),
              {"app_name": "Acrobat Reader", "category": "pdf", "activity": "idle for 30 s (foreground: Acrobat Reader)",
               "interrupt_ok_hint": True})
    assert tr.looking_at_screen is False and tr.ambient == "dark"
    p = tr.signals_payload(zoom_step=1)
    assert errors(p, "SignalsData") == []
    assert p["app"] == {"name": "Acrobat Reader", "category": "pdf", "zoom_step": 1}
    feed(tr, t, 2, face=False)
    p2 = tr.signals_payload()
    assert p2["face"] is False and p2["distance_cm"] is None and p2["looking_at_screen"] is None
    assert errors(p2, "SignalsData") == []


def test_helpers():
    assert [ambient_bucket(x) for x in (10, 60, 120, 200, None)] == ["dark", "dim", "normal", "bright", "normal"]
    assert [distance_band(x) for x in (25, 35, 60, 90, None)] == ["too_close", "close", "healthy", "far", None]
    yaw, pitch = head_angles([[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]])
    assert abs(yaw) < 1e-9 and abs(pitch) < 1e-9
