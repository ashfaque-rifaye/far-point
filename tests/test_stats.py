from myrmidon.contract import errors
from myrmidon.stats import StatsStore


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


def test_stats_schema_privacy_and_latency(runtime_dir):
    clock = Clock(1_792_650_000.0)
    s = StatsStore(runtime_dir / "profile", clock)
    for ms in (300, 400, 500, 600, 2000):
        s.record_decider_latency(ms)
    s.inc("adaptations")
    s.record_bedrock(2, 1500)
    s.update_from_tracker({"under30_min": 3.5, "squint_episodes": 2, "glasses_off_min": 0.5, "longest_bout_min": 47.2})
    snap = s.snapshot()
    assert errors(snap, "StatsData") == []
    assert snap["face_images_uploaded"] == 0
    assert snap["decisions"] == 5 and snap["decider_p50_ms"] == 500 and snap["decider_p95_ms"] > 600
    assert snap["bedrock_calls"] == 2 and snap["bedrock_tokens"] == 1500 and snap["longest_bout_min"] == 47.2
    s.save()
    again = StatsStore(runtime_dir / "profile", clock)
    assert again.snapshot()["adaptations"] == 1 and again.snapshot()["decider_p50_ms"] == 500


def test_period_and_rollover(runtime_dir):
    clock = Clock(1_792_650_000.0)
    s = StatsStore(runtime_dir / "profile", clock)
    s.inc("breaks_verified", 3)
    clock.t += 86_400
    s.inc("breaks_verified")
    days = s.period(7)
    assert [d["breaks_verified"] for d in days] == [3, 1]
    assert all("_latencies" not in d for d in days)
