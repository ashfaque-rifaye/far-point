# Far Point: a screen that adapts to your eyes, decided locally by Strands Decider 2B

Tags: `#strands-decider-2b` `#tool-selection`

Repo: https://github.com/ashfaque-rifaye/far-point (Apache-2.0) · Video: <add YouTube link>

> Not a medical device. Far Point does not diagnose, treat or prevent any eye condition.

![Far Point](images/cover.png)

*Dashboard screenshots in this article come from its built-in demo story, so the numbers in them are scripted. The results tables are measured.*

## The moment it is built for

It is late. My glasses are on the desk, the page is small, and I have crept to 26 cm from the screen without noticing. Nearsightedness is common and growing; a widely cited projection puts it at about half the world's population by 2050 (Holden et al., *Ophthalmology*, 2016). In children, reading closer than 30 cm and long unbroken stretches of near work are linked to higher myopia risk.

Apple's Screen Distance and wearables like Clouclip warn you when you are too close. Far Point tries something else: it changes the screen so that sitting back is possible, and then it checks with the camera whether you actually sat back.

## What the agent does

Every 2.5 seconds, entirely on my laptop (RTX 4060, Windows 11):

1. **Measure.** MediaPipe's face landmarks estimate distance from the size of the iris (a plain webcam, no depth sensor), plus eye opening against my calibrated baseline, blinks, head turn and room light. The foreground app comes from Win32. Frames are processed in memory and dropped.
2. **Decide.** Strands Decider 2B reads my rulebook against those numbers and decides which rules apply right now. Code applies the rulebook's priority order.
3. **Act.** A Strands Agent runs one reversible tool: enlarge or reduce text in the app I am in, dark mode, dim or brighten the screen, a 20-second far-look break, a glasses reminder, or a question.
4. **Verify.** Thirty seconds later the camera numbers decide whether it worked: did I sit back past 40 cm, did my eyes open up? A break only counts when the camera sees me look away for 20 seconds. A change that rarely works in an app gets demoted there.

Amazon Nova Lite on Bedrock does the language work: it turns my own description of my eyes into a draft rulebook that I adopt with one click, writes a numbers-only report for my optometrist, proposes new rules from moments where the Decider was unsure, and drafts an eye-exam email that opens only after I confirm. Bedrock gets words and numbers, never an image. The dashboard's privacy counter, "face images uploaded: 0", has nothing that can increment it.

## Architecture

![Architecture](images/architecture.png)

Everything left of the line runs on the laptop. Only text and numbers cross to Bedrock. More detail: `docs/ARCHITECTURE.md` in the repo.

## The decision handed to Decider 2B

![One tick of the reflex loop](images/decision-loop.png)


Declared pattern: **tool selection**. Which of nine tools, if any, should run right now?

My first design asked the Decider one 9-way `choice` question. On a preregistered held-out set it agreed with the rulebook on **68.1%** of states. It was not bad at reading the state; it was bad at applying a priority order across several true conditions.

So I split the decision the way the model is strong:

- **Code writes each fact as a verdict.** Not "27 cm" but `Viewing distance: 27 cm, under 30 cm for 8 s (limit 5 s): too close, enlarging needed.` Code does every comparison and every AND a rule needs.
- **One `noul` per rule.** "Does rule N apply right now?" with explicit `true`/`false` criteria. One request asks all eight rules plus `interrupt_ok` over the same state. That is 9 questions in about 0.45-0.6 s on the laptop GPU.
- **Code applies the order and a confidence policy.** A rule fires at p ≥ 0.65 and is clear at p ≤ 0.35. If a higher-priority rule lands in between, Far Point asks Nova Lite about just those rules, with the same text. If Nova is unavailable, it stays quiet. A wrong interruption costs more than a missed one.
- **Strands interventions sit on the tool call.** `InterruptGate` denies breaks and reminders while I am on a call, typing in a burst or watching fullscreen video, reusing the batched `interrupt_ok` answer. `ConfirmGate` puts my approval in front of adopting a rulebook or opening the email.

## Results (all synthetic states, all preregistered)

| | Tool selection | Latency per decision | Bedrock tokens (72 states) |
|---|---|---|---|
| One 9-way `choice` (Phase 1) | 68.1% | | 0 |
| Per-rule nouls + code order (Decider alone) | 87.5% | p50 574 ms | 0 |
| Nova Lite alone, all 8 rules per call | 100% | p50 2,572 ms, p90 3,179 ms | 107,500 |
| **Far Point's loop: Decider + Nova only on unsure rules** | **100%** | 458 ms; +2.2 s on 9 of 72 states | **9,522** |

What I take from it:

- **The renderer did most of the work.** The same per-rule questions over my old, descriptive text scored 30.6%. Ending every line with one verdict phrase moved per-rule accuracy to 99.7%.
- **Every Decider miss was a quiet tick, not a wrong action.** All nine misses were states where a higher-priority rule was unsure, so the policy stayed silent. Nova fixed all nine.
- **Nova Lite alone was just as accurate, but it is not a 2.5-second reflex.** Its p90 is longer than the loop period, and it needs 11x the tokens of the hybrid for the same accuracy. Over an 8-hour day an LLM-only loop would send about 17 million tokens per user to the cloud; the hybrid sends a small fraction, and only words.

The full write-ups, including the weaknesses, are in `eval/SPIKE_RESULTS.md`, `eval/S3_RESULTS.md` and `eval/S4_RESULTS.md`.

## The reusable pattern: Reflex Gate

`patterns/reflex_gate/` has no eye-specific code. It gives you:

- `Rule` + `rule_question()` + `build_questions()`: the typed `noul` per rule, plus the `interrupt_ok` question.
- `select()`: the priority order and the fire/unsure/clear policy, with an optional `escalate` callback for an LLM.
- `InterruptGate` and `ConfirmGate`: Strands `InterventionHandler`s for the tool call. Direct `agent.tool.X()` calls go through them, and a test pins that.
- `FakeDecider` and `ScriptedModel` for tests without a GPU or AWS.
- `examples/posture_agent.py`: the same pattern as a posture coach.

The README has the exact JSON of the questions, the wiring in 15 lines, and the two wording rules I learned the hard way: end each fact with one verdict phrase, and fold every AND into one line in code.

## Honest limits

- Not a medical device. The thresholds come from a pilot study of school-age children (Clouclip, *Medicine* 2020) and are applied to adults as a starting point.
- The eval states are synthetic. Real webcam facts are noisier.
- Distance from iris size is accurate to roughly 10% after calibration.
- Image mode fits on the GPU (6.56 GB peak, 0.51 s), but I did not measure its accuracy, so Far Point runs text-only. Glasses-off is inferred from distance and squint changes, not seen.

## Built with

Strands Decider 2B (`strands-decider-2B-qwen3.5-v1-2610`, local), Strands Agents with interventions, Amazon Bedrock (Nova Lite, us-east-1), MediaPipe, FastAPI, and a Vite + React dashboard.
