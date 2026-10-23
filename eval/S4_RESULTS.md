# S4: Amazon Nova Lite alone vs the Decider (results)

Preregistered in `eval/PREREGISTRATION.md` ("Phase 3: S4 LLM-only baseline"), committed in `a56086c` with `eval/spike_s4.py` before the run. One run, no prompt changes. Raw data: `results/s4_held_nova_only.json`. The Decider numbers are the existing S3 runs on the same 72 held-out states (seed 4, `new` renderer).

## Same 72 states, three ways

| Arm | Tool selection (end to end) | Latency per decision, p50 / p90 | Bedrock calls | Bedrock tokens |
|---|---|---|---|---|
| Decider 2B alone (local GPU), `s3_held_new` | 87.5% (63/72) | **574 / 612 ms** | 0 | 0 |
| Nova Lite alone (one call per state, all 8 rules), `s4_held_nova_only` | **100%** (72/72) | 2,572 / 3,179 ms | 72 | 107,500 (1,493 per state) |
| Decider, Nova Lite only on unsure rules (Myrmidon's loop), `s3_held_new_esc` | **100%** (72/72) | 458 / 533 ms for the Decider; +2,152 ms p50 on the 9 escalated states | 9 | 9,522 |

Latency is client wall clock on the RTX 4060 laptop (Decider) and from India to Bedrock us-east-1 (Nova). The Decider request also answers `interrupt_ok`; the Nova arm does not, because the escalation prompt covers rules only.

## What it shows

- On these states Nova Lite alone is as accurate as the hybrid and more accurate than the Decider alone. The Decider's advantage is not accuracy here; it is speed, locality and cost.
- **4.5x faster.** Myrmidon decides every 2.5 s. Nova Lite's p90 (3.2 s) is longer than that period, so an LLM-only loop could not keep up from this laptop. The Decider answers in about 0.6 s, locally.
- **11x fewer tokens for the same accuracy.** The hybrid reaches 100% with 9 Bedrock calls instead of 72 (12.5% of states), 9,522 tokens instead of 107,500.
- Scaled to a working day: one decision every 2.5 s for 8 hours is 11,520 decisions. Nova Lite alone at 1,493 tokens each would be about 17 million tokens per user per day, sent to the cloud. With the measured 12.5% escalation share the hybrid would send about 1.5 million, and in Myrmidon's loop it is lower again, because escalation is rate-limited (once per 10 s, 300 per day) and quiet states never escalate.
- The Decider never sees an image in either arm, and neither does Nova. Nothing about the face leaves the laptop in any of the three arms.

## Weaknesses

- One held-out set of 72 synthetic states, rendered by code into verdict phrases. That makes the task easy for any capable model; it is a fair test of latency and cost, not of hard reasoning.
- One run per arm, and network latency depends on where you are. The Bedrock numbers were measured from India to us-east-1.

## Reproduce

```powershell
.venv\Scripts\python.exe eval\spike_s4.py --seed 4 --tag held_nova_only
```
