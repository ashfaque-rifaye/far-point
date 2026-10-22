# S3: per-rule nouls + code priority (results)

Preregistered in `eval/PREREGISTRATION.md` ("Phase 2: S3 per-rule nouls", commit 85093c5), before any run. The scripts were committed next (704b929), and the runs came after that. Raw data is in `results/s3_*.json`. Thresholds were fixed at 0.35 / 0.65 and nothing was retuned.

**One 9-way choice: 68.1% → per-rule nouls + code order: 87.5%** (held-out seed 4, 63 of 72 states, no escalation). With Amazon Nova Lite judging the unsure rules it reaches 100% (72 of 72). Nova was called on 9 of 72 states, and 1.7% of rule nouls fell in the unsure band.

## Held-out results (seed 4, 72 states)

| Run | Renderer | End to end | 2-trigger states | Per-rule noul accuracy (mean) | Unsure nouls | interrupt_ok | p50 / p90 |
|---|---|---|---|---|---|---|---|
| `held_new` | new | **87.5%** (63/72), target 85%: PASS | 71.4% (10/14) | 99.7% | 1.7% | 83.3% | 574 / 612 ms |
| `held_old` (ablation) | old S1 text | 30.6% (22/72) | 14.3% (2/14) | 86.5% | 29.3% | 97.2% | 503 / 524 ms |
| `held_new_esc` | new + Nova Lite on unsure | **100%** (72/72), +12.5 points over the same run without | 100% | 99.7% | 1.7% | 83.3% | 458 / 533 ms |
| `dev_new` (seed 3, sanity only) | new | 84.7% (61/72) | 78.6% | 99.8% | 1.9% | 90.3% | 451 / 480 ms |

Latency is client wall clock for one request with 9 questions (8 rule nouls + `interrupt_ok`, about 1100 input tokens). It was measured after 5 warm-ups on the RTX 4060 laptop, with the server at High priority. **Target p50 <= 1000 ms: PASS** in every run.

Escalation run: 9 states escalated, 9 Bedrock calls, 9,522 tokens in total, Nova Lite p50 2.15 s per escalation, and no null verdicts. Nova got the same text state, never images.

## What the numbers show

- **The renderer does most of the work.** With S1's old text, the same 8 per-rule nouls reached only 30.6% end to end. 29% of nouls were unsure, so the fail-quiet policy stayed silent on 58 of 72 states, and `reduce_text` was at 26% (53 false positives). With the new renderer, code folds every condition a rule combines into one line that ends in "X needed" / "no X needed". Per-rule accuracy is then 99.7%. Said plainly: in the new setup the Decider reads verdict phrases that code computed, and code applies the priority order.
- **Every miss without escalation was fail quiet, not a wrong action.** All 9 held-out misses are states whose label is `dim_screen` (3) or `brighten_screen` (6), where the higher-priority `dim_screen` rule was unsure (7 unsure nouls, 2 false positives). The policy stayed quiet instead of acting. Escalating those 9 states to Nova Lite fixed all of them.
- **`interrupt_ok` dropped to 83.3% with the new renderer** (97.2% with the old text). The misses are "typing in a burst" (8 of 10 judged OK to interrupt) and "in a video call" (4 of 17). Those are the cases where interrupting is wrong. S3 is reported as measured. After S3, Far Point's own renderer (`farpoint/facts.py`) appends code's activity verdict to the Activity line ("...: not a good moment to interrupt"). In single-request probes with the full Far Point state, that moved a typing burst from p 0.58 to 0.43 and a video call from 0.55 to 0.25, with idle states at 0.94-0.97. In the replayed demo session, the Teams-call deny went from p 0.36 to 0.17. That change was made after S3, and S3 did not measure it.
- Two-trigger states are the weak spot without escalation: 71.4% on held-out (10/14). Phase 1 got 5/14 with the 9-way choice.

## Weaknesses

- The states are synthetic (`eval/s1_states.py`), 72 per set, and there is one held-out set. Real webcam-derived facts are noisier.
- The dev set (seed 3) came in at 84.7%, just under the 85% target. The held-out pass is not a large margin.
- The new renderer is specific to this rulebook. A rulebook written by Bedrock (`farpoint/coach.py`) may phrase rules that combine lines, and S3 does not measure that. The Phase 2 probes showed that cross-line ANDs leave the Decider unsure (p 0.37-0.69).
- Escalation adds about 2 s and a cloud call whenever a higher-priority rule is unsure. Far Point rate-limits it (once per 10 s, 300 per day) and stays quiet otherwise.

## Reproduce

```powershell
.\scripts\start_decider.ps1
.venv\Scripts\python.exe eval\spike_s3.py --seed 4 --render new --tag held_new
.venv\Scripts\python.exe eval\spike_s3.py --seed 4 --render old --tag held_old
.venv\Scripts\python.exe eval\spike_s3.py --seed 4 --render new --escalate --tag held_new_esc
```
