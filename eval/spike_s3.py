"""Spike S3: per-rule nouls + code priority on the S1 states (preregistered in eval/PREREGISTRATION.md).

  python eval/spike_s3.py --seed 4 --render new --tag held_new
  python eval/spike_s3.py --seed 4 --render old --tag held_old
  python eval/spike_s3.py --seed 4 --render new --escalate --tag held_new_esc

Writes results/s3_<tag>.json and prints a summary.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "eval"))

from s1_states import Facts, generate, label, render  # noqa: E402
from s3_rules import RULES_NEW, RULES_OLD, reference, render_s3  # noqa: E402
from spike_s1 import gpu_mem, pct  # noqa: E402

from farpoint.decide import ask  # noqa: E402
from patterns.reflex_gate import Thresholds, build_questions, select  # noqa: E402

WARMUP = 5
E2E_TARGET = 0.85
P50_TARGET_MS = 1000.0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=4)
    ap.add_argument("--render", choices=["new", "old"], default="new")
    ap.add_argument("--escalate", action="store_true")
    ap.add_argument("--tag", required=True)
    a = ap.parse_args()

    rules = RULES_NEW if a.render == "new" else RULES_OLD
    rend = render_s3 if a.render == "new" else render
    questions = build_questions(rules)
    th = Thresholds()
    items = generate(a.seed)
    escalator = None
    if a.escalate:
        from farpoint.escalate import NovaEscalator
        from farpoint.stats import StatsStore
        import os
        stats = StatsStore(Path(os.environ.get("FARPOINT_RUNTIME", r"E:\farpoint-runtime")) / "s3-eval")
        escalator = NovaEscalator(stats=stats, min_interval_s=0, daily_budget=1000, timeout_s=15)

    for it in items[:WARMUP]:
        ask(rend(Facts(**it["facts"])), questions)

    rows, client_ms = [], []
    for it in items:
        f = Facts(**it["facts"])
        state = rend(f)
        t0 = time.perf_counter()
        resp = ask(state, questions)
        client_ms.append((time.perf_counter() - t0) * 1000)
        answers = resp["answers"]
        sel = select(rules, answers, th)
        row = {
            "id": it["id"], "label": it["labels"]["next_action"], "triggers": it["triggers"],
            "p": {r.tool: answers[f"rule_{r.n}"]["noul"] for r in rules},
            "interrupt_ok_p": answers["interrupt_ok"]["noul"], "interrupt_ok_label": it["labels"]["interrupt_ok"],
            "choice": sel.tool or "none", "policy_reason": sel.reason, "unsure": sel.unsure,
            "client_ms": client_ms[-1], "server_ms": resp.get("latency_ms"),
            "input_tokens": resp.get("usage", {}).get("input_tokens"),
        }
        if escalator is not None:
            sel_e = select(rules, answers, th, escalate=lambda rs, s=state: escalator(s, rs))
            row["choice_esc"] = sel_e.tool or "none"
            row["escalation"] = sel_e.escalation
        rows.append(row)

    n = len(rows)
    ref = {r["id"]: reference(Facts(**it["facts"])) for r, it in zip(rows, items)}
    per_rule = {}
    for r in rules:
        c = defaultdict(int)
        for row in rows:
            truth, pred = ref[row["id"]][r.tool], row["p"][r.tool] > 0.5
            c[("t" if pred == truth else "f") + ("p" if pred else "n")] += 1
        per_rule[r.tool] = {"accuracy": (c["tp"] + c["tn"]) / n, "tp": c["tp"], "tn": c["tn"], "fp": c["fp"],
                            "fn": c["fn"],
                            "unsure": sum(1 for row in rows if th.clear_p < row["p"][r.tool] < th.fire_p)}
    e2e = sum(row["choice"] == row["label"] for row in rows) / n
    multi = [row for row in rows if len(row["triggers"]) > 1]
    nouls = [row["p"][r.tool] for row in rows for r in rules]
    confusion = defaultdict(lambda: defaultdict(int))
    for row in rows:
        confusion[row["label"]][row["choice"]] += 1
    summary = {
        "tag": a.tag, "seed": a.seed, "render": a.render, "escalate": a.escalate, "n_states": n,
        "n_questions_per_request": len(questions),
        "end_to_end_agreement": e2e,
        "end_to_end_agreement_multi_trigger": (sum(row["choice"] == row["label"] for row in multi) / len(multi))
        if multi else None,
        "n_multi_trigger": len(multi),
        "per_rule": per_rule,
        "per_rule_mean_accuracy": statistics.mean(v["accuracy"] for v in per_rule.values()),
        "interrupt_ok_accuracy": sum((row["interrupt_ok_p"] > 0.5) == row["interrupt_ok_label"] for row in rows) / n,
        "escalation_rate": sum(1 for p in nouls if th.clear_p < p < th.fire_p) / len(nouls),
        "states_with_unsure_above_choice": sum(1 for row in rows if row["unsure"]),
        "confusion": {k: dict(v) for k, v in confusion.items()},
        "client_ms": {"p50": statistics.median(client_ms), "p90": pct(client_ms, 0.9), "max": max(client_ms)},
        "server_ms": {"p50": statistics.median(r["server_ms"] for r in rows)},
        "mean_input_tokens": statistics.mean(r["input_tokens"] or 0 for r in rows),
        "gpu": gpu_mem(),
        "pass_end_to_end": e2e >= E2E_TARGET,
        "pass_latency": statistics.median(client_ms) <= P50_TARGET_MS,
    }
    if escalator is not None:
        e2e_esc = sum(row["choice_esc"] == row["label"] for row in rows) / n
        calls = [row for row in rows if row.get("escalation")]
        summary.update({
            "end_to_end_agreement_with_escalation": e2e_esc,
            "escalation_gain": e2e_esc - e2e,
            "states_escalated": len(calls),
            "nova_verdicts_none": sum(1 for row in calls for v in row["escalation"]["verdicts"].values() if v is None),
            "nova_latency_ms_p50": statistics.median(row["escalation"]["latency_ms"] for row in calls) if calls else None,
            "bedrock_calls": escalator.stats.get("bedrock_calls"),
            "bedrock_tokens": escalator.stats.get("bedrock_tokens"),
        })
        escalator.close()
    out = ROOT / "results" / f"s3_{a.tag}.json"
    out.write_text(json.dumps({"summary": summary, "rows": rows}, indent=2))
    print(json.dumps({k: v for k, v in summary.items() if k not in ("confusion",)}, indent=2))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
