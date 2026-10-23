"""Spike S1: Decider text decisions over synthetic labeled states.

Usage:
  python eval/spike_s1.py --seed 1 --questions v1 --tag run1
Writes results/s1_<tag>.json and prints a summary.
"""
from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "eval"))

from myrmidon.decide import ask  # noqa: E402
from s1_questions import VERSIONS  # noqa: E402
from s1_states import STRAIN_LEVELS, generate  # noqa: E402

WARMUP = 5
P50_LIMIT_MS = 600.0
AGREE_LIMIT = 0.85


def gpu_mem() -> dict:
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=name,memory.used,memory.total,utilization.gpu", "--format=csv,noheader,nounits"],
            text=True,
        ).strip()
        name, used, total, util = [x.strip() for x in out.split(",")]
        return {"name": name, "used_mib": int(used), "total_mib": int(total), "util_pct": int(util)}
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}


def pct(xs, q):
    xs = sorted(xs)
    k = (len(xs) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--questions", default="v1")
    ap.add_argument("--tag", default="run1")
    ap.add_argument("--config", default="", help="free-text runtime configuration note")
    a = ap.parse_args()

    qs = VERSIONS[a.questions]
    items = generate(a.seed)
    for it in items[:WARMUP]:
        ask(it["state"], qs)

    rows, client_ms, server_ms = [], [], []
    for it in items:
        t0 = time.perf_counter()
        resp = ask(it["state"], qs)
        client_ms.append((time.perf_counter() - t0) * 1000)
        server_ms.append(resp.get("latency_ms"))
        ans = resp["answers"]
        na = ans["next_action"]
        st = ans["strain"]
        strain_pred = STRAIN_LEVELS[min(max(round(st["score"]), 0), len(STRAIN_LEVELS) - 1)]
        rows.append({
            "id": it["id"],
            "label": it["labels"],
            "triggers": it["triggers"],
            "pred": {
                "next_action": na["choice"],
                "next_action_conf": na["confidence"],
                "strain": strain_pred,
                "strain_score": st["score"],
                "interrupt_ok_p": ans["interrupt_ok"]["noul"],
            },
            "client_ms": client_ms[-1],
            "server_ms": server_ms[-1],
            "input_tokens": resp.get("usage", {}).get("input_tokens"),
        })

    n = len(rows)
    agree = sum(r["pred"]["next_action"] == r["label"]["next_action"] for r in rows) / n
    strain_acc = sum(r["pred"]["strain"] == r["label"]["strain"] for r in rows) / n
    intr_acc = sum((r["pred"]["interrupt_ok_p"] > 0.5) == r["label"]["interrupt_ok"] for r in rows) / n
    multi = [r for r in rows if len(r["triggers"]) > 1]
    multi_agree = (sum(r["pred"]["next_action"] == r["label"]["next_action"] for r in multi) / len(multi)) if multi else None

    confusion = defaultdict(Counter)
    for r in rows:
        confusion[r["label"]["next_action"]][r["pred"]["next_action"]] += 1
    per_label = {k: v[k] / sum(v.values()) for k, v in confusion.items()}

    p50 = statistics.median(client_ms)
    summary = {
        "tag": a.tag,
        "seed": a.seed,
        "questions": a.questions,
        "config": a.config,
        "n_states": n,
        "n_questions_per_request": len(qs),
        "next_action_agreement": agree,
        "next_action_agreement_multi_trigger": multi_agree,
        "n_multi_trigger": len(multi),
        "strain_accuracy": strain_acc,
        "interrupt_ok_accuracy": intr_acc,
        "per_label_agreement": per_label,
        "confusion": {k: dict(v) for k, v in confusion.items()},
        "client_ms": {"p50": p50, "p90": pct(client_ms, 0.9), "min": min(client_ms), "max": max(client_ms)},
        "server_ms": {"p50": statistics.median(server_ms), "p90": pct(server_ms, 0.9)},
        "mean_input_tokens": statistics.mean(r["input_tokens"] or 0 for r in rows),
        "gpu": gpu_mem(),
        "pass_agreement": agree >= AGREE_LIMIT,
        "pass_latency": p50 <= P50_LIMIT_MS,
    }
    summary["pass"] = summary["pass_agreement"] and summary["pass_latency"]
    out = ROOT / "results" / f"s1_{a.tag}.json"
    out.write_text(json.dumps({"summary": summary, "rows": rows}, indent=2))
    print(json.dumps(summary, indent=2))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
