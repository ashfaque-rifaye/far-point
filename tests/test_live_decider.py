"""Live: one real request to the local Decider (needs `scripts/start_decider.ps1`)."""
import time

import pytest

from myrmidon.decide import client
from myrmidon.doctrine import default_doctrine
from myrmidon.facts import Facts, render_state
from patterns.reflex_gate import build_questions, select


@pytest.mark.live
def test_real_decider_fires_rule_1_on_a_too_close_state():
    c = client()
    assert c.health(), "Decider is not up on 127.0.0.1:8099 (run scripts/start_decider.ps1)"
    d = default_doctrine()
    f = Facts(face=True, distance_cm=27, under_near_s=8, squint_ratio=0.8, blink_per_min=14, usual_distance_cm=52,
              room="normal", brightness_pct=55, theme="light", app_name="Acrobat Reader", app_category="pdf",
              zoom_available=True, bout_min_now=12, activity="idle for 30 s (foreground: Acrobat Reader)")
    rules = d.to_pattern_rules()
    qs = build_questions(rules)
    assert len(qs) == 9  # 8 rule nouls + interrupt_ok
    c.ask(render_state(f, d), qs, timeout=300)  # warm-up (not timed)
    t0 = time.perf_counter()
    resp = c.ask(render_state(f, d), qs, timeout=60)
    ms = (time.perf_counter() - t0) * 1000
    p1 = resp["answers"]["rule_1"]["noul"]
    sel = select(rules, resp["answers"])
    print(f"\nrule_1 p={p1:.3f} interrupt_ok={resp['answers']['interrupt_ok']['noul']:.3f} "
          f"client={ms:.0f} ms server={resp.get('latency_ms')} ms tokens={resp.get('usage')}")
    assert p1 >= 0.65
    assert sel.tool == "enlarge_text" and sel.policy == "act"
