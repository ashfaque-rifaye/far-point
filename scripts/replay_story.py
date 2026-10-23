"""Run a replay trace through the real loop inline (no server, no waiting) and print the story:
every non-quiet decision, action, verification and break phase.

  python scripts/replay_story.py                      # demo trace, FAKE oracle Decider, dry-run actuators
  python scripts/replay_story.py --real-decider       # same trace, the real local Decider on 127.0.0.1:8099

Runtime data goes to a scratch profile under MYRMIDON_RUNTIME (never the live profile).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from myrmidon.config import DEFAULT_TRACE, Settings  # noqa: E402
from myrmidon.contract import errors  # noqa: E402
from myrmidon.predicates import PREDICATES  # noqa: E402
from myrmidon.runtime import Runtime  # noqa: E402
from myrmidon.sources import load_trace  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace", type=Path, default=DEFAULT_TRACE)
    ap.add_argument("--real-decider", action="store_true")
    ap.add_argument("--json", type=Path, help="also write the event list here")
    a = ap.parse_args(argv)
    scratch = Path(os.environ.get("MYRMIDON_RUNTIME", r"E:\myrmidon-runtime")) / "scratch-story"
    shutil.rmtree(scratch, ignore_errors=True)
    s = Settings(mode="replay", trace=a.trace, runtime_dir=scratch, fake_decider=not a.real_decider, no_bedrock=True)
    rt = Runtime(s, bedrock_available=False, deny_without_client=False)
    events: list[dict] = []
    rt.bus.add_listener(events.append)

    # Per-rule agreement of the Decider with the reference predicates, on this trace's states.
    agree: dict[str, list[int]] = {}
    real_ask = rt.decider.ask

    def scored_ask(state, questions, images=None, timeout=None):
        resp = real_ask(state, questions, images=images, timeout=timeout)
        f, d = rt.loop.current_facts, rt.store.active
        for name, ans in resp.get("answers", {}).items():
            if name.startswith("rule_"):
                rule = d.rule(int(name.split("_")[1]))
                want = PREDICATES[rule.tool](f, d.limits)
                p = ans["noul"]
                key = f"{rule.n}:{rule.tool}"
                c = agree.setdefault(key, [0, 0, 0])  # agree, total, unsure
                c[0] += int((p > 0.5) == want)
                c[1] += 1
                c[2] += int(0.35 < p < 0.65)
        return resp

    rt.decider.ask = scored_ask
    _, rows = load_trace(a.trace)
    rt.source._apply_header()
    last = {"process": None}
    t0 = rt.clock.base
    for r in rows:
        rt.source.feed(r, last)
    rt.publish_stats()
    bad = 0
    for e in events:
        if errors(e, "ServerEvent"):
            bad += 1
        d, ty = e["data"], e["type"]
        if ty == "decision" and d["policy"] != "quiet":
            print(f"DECISION {d['id']} policy={d['policy']} choice={d['answers']['next_action']['choice']} "
                  f"{d.get('rule_ref', '')} interrupt_ok={d['answers']['interrupt_ok']['p']} "
                  f"latency={d['latency_ms']}ms source={d['source']}")
        elif ty == "action":
            g = d["gate"]
            print(f"  ACTION {d['id']} {d['tool']} -> {d['status']} gate={g['name']}:{g['verdict']}:{g['p']} "
                  f"| {d['message']}")
        elif ty == "verification":
            print(f"  VERIFY {d['action_id']} -> {d['outcome']} before={d['before']} after={d['after']} "
                  f"window={d['window_s']}s")
        elif ty == "break" and d["phase"] != "tick":
            print(f"  BREAK {d['id']} {d['phase']} looking_away={d['looking_away_s']}s streak={d['streak']}")
    n_dec = sum(1 for e in events if e["type"] == "decision")
    stats = rt.stats.snapshot()
    print(f"\n{len(rows)} trace rows, {n_dec} decisions, {len(events)} events, schema errors: {bad}")
    print("stats:", json.dumps({k: stats[k] for k in ("decisions", "adaptations", "adaptations_worked",
                                                      "breaks_offered", "breaks_verified", "face_images_uploaded",
                                                      "decider_p50_ms")}))
    if a.real_decider:
        print("per-rule agreement with the reference predicates (agree/total, unsure band 0.35-0.65):")
        for key, (ok, n, unsure) in sorted(agree.items(), key=lambda kv: int(kv[0].split(":")[0])):
            print(f"  rule {key}: {ok}/{n} ({ok / n:.0%}), unsure {unsure}")
    rt.actuators.restore_all()
    print("dry-run actuators after restore:", rt.actuators.state(), "journal:", rt.actuators.journal.entries())
    if a.json:
        a.json.write_text(json.dumps(events, indent=1))
    rt.coach.close()
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
