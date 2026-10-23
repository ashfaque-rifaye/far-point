# Myrmidon architecture

![Architecture](images/architecture.png)

Myrmidon is one agent loop on a Windows laptop plus a coach on Amazon Bedrock. The loop runs every 2.5 s: measure, decide, act, verify. Strands Decider 2B makes the per-tick decision on the local GPU. Amazon Nova Lite on Bedrock is used for language (rulebook, reports, proposals, email draft) and as a second opinion when the Decider is unsure. Nothing that leaves the laptop is an image.

Source: [`scripts/video_scenes.html`](../scripts/video_scenes.html), the same scenes the demo video animates. `scripts/render_doc_images.py` renders their last frame to these PNGs.

Reading the diagram: solid arrows run on the laptop every tick; dashed orange arrows cross to Amazon Bedrock, and carry only text and numbers. Bedrock is called on a tick only when a rule is unsure (9 of 72 held-out states); the coach runs when you ask for a rulebook, a report or the email draft.

## One tick

![Decision loop](images/decision-loop.png)

| Step | What happens | Code |
|---|---|---|
| Measure | MediaPipe FaceLandmarker on the webcam frame: distance from iris diameter (calibrated focal length), eye opening against your baseline, blinks, head yaw/pitch, frame brightness. The frame is dropped after this. The foreground window, typing, fullscreen and calls come from Win32 | `myrmidon/sense.py`, `myrmidon/signals.py`, `myrmidon/context.py` |
| Render | Code compares every number against the rulebook's limits and writes one line per fact, ending in a verdict phrase ("enlarging needed" / "no enlarging needed"). Strain is counted here, in code | `myrmidon/facts.py` |
| Decide | One request to the local Decider with one `noul` per candidate rule plus `interrupt_ok`, over that text. Rules that cannot apply this tick (cooldown, zoom at cap, demoted in this app, break running) are skipped before asking | `myrmidon/loop.py`, `patterns/reflex_gate/questions.py`, `myrmidon/decide.py` |
| Policy | Rules walked in priority order: fires at p ≥ 0.65, clear at p ≤ 0.35, unsure between. The first firing rule wins unless a rule above it is unsure; then Nova Lite judges only those rules on the same text. No verdict means quiet | `patterns/reflex_gate/policy.py`, `myrmidon/escalate.py` |
| Act | The chosen tool runs as `agent.tool.<name>()` on a Strands Agent whose model is never called in the loop. `InterruptGate` (primed with the batched `interrupt_ok`) and `ConfirmGate` are Strands interventions on that call | `myrmidon/agent.py`, `myrmidon/tools.py`, `patterns/reflex_gate/gate.py` |
| Actuate | Zoom keys to allowlisted apps only, `AppsUseLightTheme`, WMI brightness, a Tk overlay for breaks. Each original is journaled before the change | `myrmidon/act.py`, `myrmidon/breaks.py` |
| Verify | 30 s later: distance and eye opening before vs after decide `worked` / `no_change` / `worse`. A break is verified by 20 s of looking away. Tools that fail three times in an app are demoted there | `myrmidon/verify.py`, `myrmidon/memory.py` |
| Publish | Every step is an event on the bus, streamed to the dashboard over one WebSocket | `myrmidon/bus.py`, `myrmidon/dashboard.py`, `docs/ui-contract.md` |

## Components and processes

| Process | Listens on | Notes |
|---|---|---|
| Strands Decider server (`strands-decider serve`, model `StrandsAgents/strands-decider-2B-qwen3.5-v1-2610`) | 127.0.0.1:8099 | Text mode, CUDA, High priority (`scripts/start_decider.ps1`). Calls are serialized behind one process-wide lock because of the engine's concurrency issue. Weights and caches on `E:\myrmidon-runtime` |
| Myrmidon backend (`python -m myrmidon.app`) | 127.0.0.1:8765 | FastAPI + uvicorn owns the asyncio loop. The signal source, reflex loop and break sessions are worker threads; events cross to WebSocket queues with `call_soon_threadsafe`. Coach calls run on a 1-worker pool so Bedrock never blocks the loop. Tk overlays run on one Tk thread |
| Dashboard | served by the backend from `web/dist` | Vite + React + TypeScript. Validates every frame against the contract guards and drops unknown types |
| Amazon Bedrock, us-east-1 | | `us.amazon.nova-lite-v1:0` through Strands `BedrockModel`, temperature 0. Escalation is rate-limited to 1 per 10 s and 300 per day |

## What crosses the network

| From → to | Content | Never |
|---|---|---|
| Backend → Bedrock (escalation) | The rendered text state and the unsure rules | images, raw face landmarks, window titles |
| Backend → Bedrock (coach) | Your eye description (when you type one), daily counters, unsure-moment notes | images |
| Browser ↔ backend | Contract events and commands over `ws://127.0.0.1:8765/ws` | anything off the machine |

`DeciderHttpClient` refuses to send an image to any non-localhost URL. The dashboard's "face images uploaded" counter has no code path that increments it (`myrmidon/privacy.py`).

## Trust boundaries and safety

- Both servers bind to 127.0.0.1. The backend rejects other Host headers and non-localhost WebSocket Origins (blocks cross-site WebSocket hijacking from other tabs).
- Everything the agent changes is reversible and journaled to `<runtime>/restore.json` first; `restore_all()` runs on exit, on Ctrl+C, and on the next start after a crash. The `reset` tool undoes everything now.
- Consequential steps need you: adopting a rulebook, approving a learned rule, opening the exam-email draft. The email is never sent by Myrmidon.
- Fail quiet: Decider timeout (> 4 s), Bedrock down, rate limit or an unsure rule with no second opinion all mean no action this tick.

## Modes

| Mode | Command | Uses |
|---|---|---|
| Live | `python -m myrmidon.app --mode live` (`--dry-run` to never touch the screen) | camera, Decider, Bedrock |
| Replay | `python -m myrmidon.app --mode replay --trace myrmidon\replay\demo_session.jsonl` | recorded numbers through the real loop, Decider and gates; dry-run actuators |
| Offline UI demo | open `http://127.0.0.1:8765/?demo=1` | scripted story in the browser, labelled DEMO |
| Tests | `python -m pytest -q` | fakes only: no GPU, camera or AWS |

## The reusable piece

`patterns/reflex_gate/` is the decision pattern without anything eye-specific: typed questions, the policy, the two interventions, a Decider client with the lock, and fakes for tests. [`patterns/reflex_gate/README.md`](../patterns/reflex_gate/README.md) shows the wiring and a posture-coach example.
