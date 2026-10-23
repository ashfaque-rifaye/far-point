"""Spike S4: Amazon Nova Lite alone on the S3 held-out states (preregistered in eval/PREREGISTRATION.md, Phase 3).

  python eval/spike_s4.py --seed 4 --tag held_nova_only

One Bedrock call per state asks about all 8 rules (text only); code applies the rulebook order.
Writes results/s4_<tag>.json and prints a summary.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "eval"))

from s1_states import Facts, generate  # noqa: E402
from s3_rules import RULES_NEW, reference, render_s3  # noqa: E402
from spike_s1 import pct  # noqa: E402

from myrmidon.escalate import NovaEscalator  # noqa: E402
from myrmidon.stats import StatsStore  # noqa: E402


def choose(rules, verdicts: dict) -> str:
    for r in rules:  # priority order
        v = verdicts.get(r.n)
        if v is None:
            return "none"  # no verdict above the first true rule: stay quiet
        if v:
            return r.tool
    return "none"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=4)
    ap.add_argument("--tag", required=True)
    a = ap.parse_args()

    rules = RULES_NEW
    items = generate(a.seed)
    stats = StatsStore(Path(os.environ.get("MYRMIDON_RUNTIME", r"E:\myrmidon-runtime")) / "s4-eval")
    nova = NovaEscalator(stats=stats, min_interval_s=0, daily_budget=1000, timeout_s=30)
    tok0 = stats.get("bedrock_tokens") or 0

    rows, ms = [], []
    for it in items:
        f = Facts(**it["facts"])
        state = render_s3(f)
        t0 = time.perf_counter()
        verdicts = nova(state, rules)
        ms.append((time.perf_counter() - t0) * 1000)
        rows.append({"id": it["id"], "label": it["labels"]["next_action"], "triggers": it["triggers"],
                     "verdicts": {str(k): v for k, v in verdicts.items()}, "choice": choose(rules, verdicts),
                     "client_ms": ms[-1]})
    nova.close()

    n = len(rows)
    per_rule = {}
    for r in rules:
        ok = sum(1 for row, it in zip(rows, items)
                 if row["verdicts"].get(str(r.n)) is not None
                 and row["verdicts"][str(r.n)] == reference(Facts(**it["facts"]))[r.tool])
        per_rule[r.tool] = ok / n
    multi = [row for row in rows if len(row["triggers"]) > 1]
    tokens = (stats.get("bedrock_tokens") or 0) - tok0
    summary = {
        "tag": a.tag, "seed": a.seed, "model": nova.model_id, "n_states": n,
        "end_to_end_agreement": sum(row["choice"] == row["label"] for row in rows) / n,
        "end_to_end_agreement_multi_trigger": sum(row["choice"] == row["label"] for row in multi) / len(multi) if multi else None,
        "per_rule_accuracy": per_rule,
        "per_rule_mean_accuracy": statistics.mean(per_rule.values()),
        "states_with_missing_verdict": sum(1 for row in rows if any(v is None for v in row["verdicts"].values())),
        "client_ms": {"p50": statistics.median(ms), "p90": pct(ms, 0.9), "max": max(ms)},
        "bedrock_tokens_total": tokens,
        "bedrock_tokens_per_state": tokens / n,
    }
    out = ROOT / "results" / f"s4_{a.tag}.json"
    out.write_text(json.dumps({"summary": summary, "rows": rows}, indent=2))
    print(json.dumps(summary, indent=2))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
