# Phase 1 feasibility spike: results

Thresholds and method were fixed in `eval/PREREGISTRATION.md` before any run. Raw metrics are in `results/s1_*.json` and `results/s2_latency.json`.

## Outcome

| Gate | Result | Numbers |
|---|---|---|
| S1 agreement (>= 85%) | FAIL | 68.1% best (v2 wording, held-out seed 2: 49/72) |
| S1 latency (p50 <= 600 ms, 3 questions) | PASS | 490 ms p50, 514 ms p90 (v2, server at High priority) |
| S2 VRAM fit (peak <= 7.4 GB) | PASS | peak 6560 MiB total; vision server footprint 4733 MiB |
| S2 latency (p50 <= 1.5 s) | PASS | 0.51 s p50, 0.54 s p90, 0.57 s max (40 live frames, 3 nouls) |
| S2 accuracy (>= 85% glasses_on, looking_far_away) | NOT MEASURED | no one was available to pose for the guided labeled capture |

**MODE DECISION: Decider TEXT-ONLY.** S2 accuracy was not measured, and the preregistration counts unmeasured as not passed. Perception comes from MediaPipe plus foreground-window context. The GPU path works, so no CPU fallback is needed. Image mode fits in VRAM and is fast enough, so it can be turned on later if a labeled capture passes (see "Re-opening S2").

S1 failed on agreement after the one allowed retune. Per the decision rule, the build proceeds with the better version (v2, `eval/s1_questions.py`) and reports the number as measured.

## Machine and conditions

- RTX 4060 Laptop (8188 MiB, driver 591.91), Ryzen 7 7435HS, AC power, Windows "Performance" power plan, native Windows (no WSL).
- The laptop was busy throughout: CPU load around 80% (Android emulator / qemu, Ollama, EA Desktop, Creative Cloud, Teams, about 90 Edge/WebView processes). GPU memory with no Decider loaded was 1827 MiB. These apps belong to the user and were not closed.
- Model `StrandsAgents/strands-decider-2B-qwen3.5-v1-2610`, `strands-decider serve --device cuda`, 127.0.0.1:8099, every call behind the lock in `myrmidon/decide.py`.

## S1: text decisions

72 synthetic states per run (8 per label), from `eval/s1_states.py`. Code computes every number and comparison and renders it in words. One request = 3 questions: `next_action` (choice, 9 options), `strain` (score, 3 levels), `interrupt_ok` (noul). About 960 input tokens per request. 14 of 72 states carry two triggers, where the doctrine's priority order decides.

| Run | Questions | Set | Runtime config | next_action | 2-trigger states | strain | interrupt_ok | p50 | p90 |
|---|---|---|---|---|---|---|---|---|---|
| run1 | v1 | seed 1 | torch reference kernels | 66.7% | 0/14 | 41.7% | 75.0% | 860 ms | 939 ms |
| run1 | v1 | seed 1 | + triton-windows, flash-linear-attention | 68.1% | 0/14 | 41.7% | 76.4% | 715 ms | 776 ms |
| run1 | v1 | seed 1 | + server process priority High | 68.1% | 0/14 | 41.7% | 76.4% | 473 ms | 499 ms |
| run2 (retune) | v2 | seed 2 | same as above | **68.1%** | 5/14 | 44.4% | **100%** | **490 ms** | 514 ms |
| reference | v1 | seed 2 | same as above | 68.1% | 1/14 | 36.1% | 80.6% | 479 ms | 508 ms |

The reference row is not a retune. It runs the original v1 wording on the held-out seed-2 set so v1 and v2 can be compared on the same items.

Per-label agreement, v2 on seed 2: far_look_break 100%, dim_screen 100%, none 100%, ask_user 88%, glasses_reminder 75%, brighten_screen 75%, enlarge_text 62%, reduce_text 12%, dark_mode 0%.

What the errors show:

- **Priority order is the main failure.** With v1, all 14 two-trigger states went to the lower-priority action, mostly `far_look_break`. v2 lists options in priority order and states in each criterion what it outranks, which raised this to 5/14. The remaining misses still mostly pick `far_look_break`.
- **dark_mode was 0-12% in every run.** "Room light: dark" plus "Theme: light" does not move the model to dark_mode. The rendered line "Screen brightness N%: balanced with the room" in those states may pull it toward `none`. That is a state-rendering issue. The retune rule allowed only question wording to change, so the rendering was left alone.
- **reduce_text dropped from 100% (v1) to 12% (v2).** v2's "and no option above holds" clause pushed these states to `none`.
- **interrupt_ok reached 100% with v2.** Its criteria name the Activity line to read and list the true and false cases explicitly.
- **strain stays near chance** (36-44%). The model predicts `mild` for almost everything. Counting signs is arithmetic, which the design says code should do.

Latency notes:

- Native Windows with transformers' reference kernels: 860 ms p50.
- Installing `triton-windows==3.7.1.post27` and `flash-linear-attention==0.5.2`: 715 ms. The first request after a fresh Triton cache autotunes for about 140 s. Do not send a second request while that runs: two overlapping autotunes crashed with `TypeError: 'NoneType' object is not a mapping`. The cache is at `E:\myrmidon-runtime\triton-cache`.
- Raising the server process to High priority: 473-490 ms. On this loaded CPU, inference is launch-bound. The GPU stayed at P3 / about 1.1 GHz during runs. `scripts/start_decider.ps1` applies High priority and the E: cache paths.
- Floor check: 2 short nouls took 610 ms at normal priority and 458 ms at High, against the 184 ms precedent. The difference is most likely the CPU load from other apps. `causal_conv1d` still uses the torch fallback because no Windows wheel is installed.

## S2: image mode (`--vision`)

| Measure | Value |
|---|---|
| GPU memory, no Decider loaded | 1827 MiB |
| GPU memory, vision server idle | 6388 MiB |
| Peak during 40 image requests | 6560 MiB (limit 7577 MiB). Fits, with about 1.6 GB free |
| Vision server footprint | 4733 MiB (the text server is about 4.0-4.5 GB) |
| Latency, 1 frame (448 px long side) + 3 nouls | p50 0.508 s, p90 0.544 s, max 0.567 s |
| Accuracy | not measured: no labeled frames |

Setup fix: `--vision` first failed with `OSError: Can't load image processor for 'Qwen/Qwen3.5-2B-Base'` because `HF_HUB_OFFLINE=1` was set and `preprocessor_config.json` had never been downloaded. Fetching the two small processor configs into `E:\myrmidon-runtime\hf` fixed it.

The live frames stayed in memory and none were written to disk. The mean P(true) on those unlabeled frames was glasses_on 0.19, rubbing_eyes 0.16 and looking_far_away 0.56. Without labels these numbers do not measure accuracy.

### Re-opening S2

Takes about 2 minutes with a person at the webcam. Frames go to `E:\myrmidon-runtime\s2-frames`, outside the repo.

```powershell
.\scripts\start_decider.ps1 -Vision
.venv\Scripts\python.exe eval\spike_s2.py capture   # 6 prompted poses x 8 frames = 48 labeled frames
.venv\Scripts\python.exe eval\spike_s2.py score     # glasses_on / looking_far_away accuracy vs 85%
.\scripts\start_decider.ps1                         # back to text mode
```

If both gated questions reach 85% or more, image mode can be turned on. VRAM fit and latency already pass.

## Notes for the build

- Proceed in text-only mode with v2 question wording. Restart the server with `scripts/start_decider.ps1` (High priority, caches on E:).
- At 68% agreement, a single Decider choice should not be trusted to apply the doctrine's 9-way priority chain. The facts are already computed in code, so the priority order can be resolved in code. The Decider is then left with the judgments it handled well here, such as `interrupt_ok`, and the fuzzy perception calls. This is a recommendation for the next phase. The spike did not test it.
- Latency leaves room for a 4th question within the 600 ms budget (about 490 ms for 3).
