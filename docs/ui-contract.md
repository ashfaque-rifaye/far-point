# Myrmidon UI contract (protocol v1)

The data contract between the Myrmidon web UI (`web/`) and the local Python backend. Three files describe the same contract and must stay in sync:

| File | Role |
| --- | --- |
| `web/src/contract.ts` | TypeScript types, runtime guards (`parseServerMessage`, `isClientCommand`), `makeCommand`, `resolveWsUrl`, and the examples below as `EXAMPLE_EVENTS` / `EXAMPLE_COMMANDS` |
| `web/contract.schema.json` | JSON Schema (draft 2020-12). `#/$defs/ServerEvent` for server frames, `#/$defs/ClientCommand` for client frames |
| `docs/ui-contract.md` | This document |

## Transport

- One WebSocket. Default URL: `ws://127.0.0.1:8765/ws`.
- Override order: `?ws=<url>` query param, then `VITE_WS_URL` build-time env, then the default. Only `ws://` and `wss://` URLs are accepted.
- The backend serves the built UI at `http://127.0.0.1:8765/` from `web/dist`.
- Each WebSocket frame is one UTF-8 JSON object. No batching.
- The backend binds to 127.0.0.1 only. There is no authentication on the socket, so it must never be bound to a public interface.

### Connection lifecycle

1. Client opens the socket. It sends nothing until it receives `hello`.
2. Backend immediately sends, in order: `hello`, `doctrine` (current), any `proposal` with status `pending`, `stats`. Then `signals` / `decision` / etc. stream normally.
3. Backend re-sends `hello` whenever any status inside it changes (decider loading to ready, camera paused, Bedrock down).
4. On disconnect the UI shows an offline state and reconnects with backoff (1 s, 2 s, 4 s, capped at 10 s). The backend replays step 2 on every new connection, so the UI never needs to ask for state.

### Envelope

Server to client:

```json
{ "v": 1, "type": "signals", "t": 1767225600200, "data": { } }
```

| Field | Type | Notes |
| --- | --- | --- |
| `v` | `1` | Protocol version |
| `type` | string | One of the event types below |
| `t` | number | Server send time, epoch ms |
| `data` | object | Payload for `type` |

Client to server:

```json
{ "v": 1, "type": "cmd", "name": "pause_camera", "args": { "paused": true } }
```

### Compatibility rules

- Receivers ignore unknown fields.
- The UI ignores unknown event types (the guard returns `unknown_type`; the UI logs and drops it).
- The backend answers an unknown command name or invalid args with a `toast` of level `warning`.
- New fields are added as optional. A breaking change bumps `v`.

### Extensions to the original brief

All are optional and backward compatible.

| Where | Field | Meaning |
| --- | --- | --- |
| `hello.bedrock.status` | value `"off"` | Bedrock disabled or no credentials. `hello.bedrock.model` is `null` then |
| `email_draft` | `to?: string \| null` | Recipient (eye clinic) if known |
| any command | `t?: number` | Client send time, epoch ms. `makeCommand` sets it; backend must not require it |

### Value conventions

- IDs are opaque strings. Prefixes used in examples (`d_`, `a_`, `b_`, `p_`, `r_`, `e_`, `c_`) are a convention, not a requirement.
- Probabilities are numbers in [0, 1]. Probability maps (`probs`) are `option -> probability` and should sum to about 1.
- Distances are centimetres; durations in `*_s` are seconds, `*_min` minutes, `*_ms` milliseconds.
- `null` means "unknown right now" (no face, low confidence), never "false".

---

## Server to client events

### `hello`

Sent on connect and whenever a status changes.

| Field | Type |
| --- | --- |
| `mode` | `'live' \| 'replay'` (replay streams a recorded session through the same events) |
| `app_version` | string |
| `profile_name` | string |
| `decider` | `{ status: 'ready'\|'loading'\|'down', model: string, device: string, vision: boolean }` |
| `bedrock` | `{ status: 'ready'\|'loading'\|'down'\|'off', model: string \| null }` |
| `camera` | `{ status: 'on'\|'off'\|'paused'\|'error' }` |

`decider.vision` true means `decision.answers.vision` will be present.

```json
{
  "v": 1, "type": "hello", "t": 1767225600000,
  "data": {
    "mode": "live",
    "app_version": "0.1.0",
    "profile_name": "Ashfaque",
    "decider": { "status": "ready", "model": "qwen2.5-vl-3b-instruct-q4", "device": "cuda", "vision": true },
    "bedrock": { "status": "ready", "model": "anthropic.claude-sonnet-4" },
    "camera": { "status": "on" }
  }
}
```

### `signals`

Perception summary at 5 to 10 Hz. The UI renders the latest one and may keep a short ring buffer for sparklines.

| Field | Type | Notes |
| --- | --- | --- |
| `face` | boolean | Face detected |
| `distance_cm` | number \| null | Eye-to-screen distance |
| `distance_band` | `'too_close'\|'close'\|'healthy'\|'far'\|null` | |
| `squint` | number | Eye-opening ratio vs calibrated baseline. 1.0 = baseline, lower = more squint |
| `squinting` | boolean | Backend's thresholded verdict |
| `blink_per_min` | number | Rolling rate |
| `looking_at_screen` | boolean \| null | |
| `ambient` | `'dark'\|'dim'\|'normal'\|'bright'` | |
| `glasses_on` | boolean \| null | |
| `bout_s` | number | Current continuous near-work bout, seconds |
| `under30_today_s` | number | Seconds closer than 30 cm today |
| `app` | `{ name: string, category: 'browser'\|'editor'\|'office'\|'pdf'\|'video'\|'meeting'\|'other', zoom_step: integer }` | `zoom_step` is the net zoom Myrmidon applied; 0 = untouched |

```json
{
  "v": 1, "type": "signals", "t": 1767225600200,
  "data": {
    "face": true,
    "distance_cm": 27.4,
    "distance_band": "too_close",
    "squint": 0.71,
    "squinting": true,
    "blink_per_min": 9.5,
    "looking_at_screen": true,
    "ambient": "dim",
    "glasses_on": false,
    "bout_s": 1840,
    "under30_today_s": 2710,
    "app": { "name": "Acrobat Reader", "category": "pdf", "zoom_step": 0 }
  }
}
```

### `decision`

One decider pass, every 2 to 3 s. The local decider answers a fixed set of questions as probability distributions; the policy layer turns them into `act`, `quiet` or `ask`.

| Field | Type | Notes |
| --- | --- | --- |
| `id` | string | Referenced by `action.decision_id` |
| `latency_ms` | number | Decider wall time |
| `source` | `'decider'\|'fallback'` | `fallback` = rule-based path when the decider is down or slow |
| `state_text` | string | The natural-language state the decider saw |
| `answers.next_action` | `{ choice: string, confidence: Prob, probs: ProbMap }` | Options are tool names plus `"none"` |
| `answers.strain` | `{ level: 'relaxed'\|'mild'\|'strong', expected: number, probs: ProbMap }` | `expected` in [0, 2]: probability-weighted 0 relaxed, 1 mild, 2 strong |
| `answers.interrupt_ok` | `{ p: Prob }` | Feeds `InterruptGate` |
| `answers.vision?` | `{ glasses_on, rubbing_eyes, looking_far, video_call }`, each a Prob | Only when `hello.decider.vision` is true |
| `policy` | `'act'\|'quiet'\|'ask'` | |
| `rule_ref?` | string | Doctrine rule that drove the policy, e.g. `"rule 2"` |

```json
{
  "v": 1, "type": "decision", "t": 1767225602400,
  "data": {
    "id": "d_000142",
    "latency_ms": 312,
    "source": "decider",
    "state_text": "Reading a PDF at 27 cm for 30 min, squint 0.71 vs baseline, dim room, glasses off, blink 9.5/min.",
    "answers": {
      "next_action": {
        "choice": "enlarge_text",
        "confidence": 0.64,
        "probs": { "enlarge_text": 0.64, "far_look_break": 0.18, "glasses_reminder": 0.11, "none": 0.07 }
      },
      "strain": { "level": "mild", "expected": 1.21, "probs": { "relaxed": 0.14, "mild": 0.51, "strong": 0.35 } },
      "interrupt_ok": { "p": 0.78 },
      "vision": { "glasses_on": 0.06, "rubbing_eyes": 0.03, "looking_far": 0.02, "video_call": 0.01 }
    },
    "policy": "act",
    "rule_ref": "rule 2"
  }
}
```

### `action`

A tool call the agent made or tried to make. The same `id` may be re-sent with a new `status` (for example `pending_confirm` then `done`); the UI replaces by `id`.

| Field | Type | Notes |
| --- | --- | --- |
| `id` | string | |
| `decision_id` | string | |
| `tool` | `'enlarge_text'\|'reduce_text'\|'dim_screen'\|'brighten_screen'\|'dark_mode'\|'far_look_break'\|'glasses_reminder'\|'ask_user'\|'reset'` | |
| `args` | object | Tool-specific, e.g. `{ "steps": 1 }`, `{ "level": 0.7 }` |
| `gate` | `{ name: 'InterruptGate'\|'Confirm'\|null, verdict: 'proceed'\|'deny'\|'defer'\|'pending'\|null, p: Prob\|null }` | `null`s when no gate applied |
| `status` | `'done'\|'denied'\|'deferred'\|'pending_confirm'\|'failed'` | |
| `message` | string | User-facing sentence |

```json
{
  "v": 1, "type": "action", "t": 1767225602450,
  "data": {
    "id": "a_000057",
    "decision_id": "d_000142",
    "tool": "enlarge_text",
    "args": { "steps": 1 },
    "gate": { "name": "InterruptGate", "verdict": "proceed", "p": 0.78 },
    "status": "done",
    "message": "Text enlarged one step so you can lean back."
  }
}
```

### `verification`

Closed-loop check of an action, `window_s` seconds after it ran.

| Field | Type |
| --- | --- |
| `action_id` | string |
| `outcome` | `'worked'\|'no_change'\|'worse'\|'n/a'` |
| `before` | `{ distance_cm: number\|null, squint: number\|null }` |
| `after` | `{ distance_cm: number\|null, squint: number\|null }` |
| `window_s` | number |

`n/a` is used when no face was visible for the window; measures are then `null`.

```json
{
  "v": 1, "type": "verification", "t": 1767225632450,
  "data": {
    "action_id": "a_000057",
    "outcome": "worked",
    "before": { "distance_cm": 27.4, "squint": 0.71 },
    "after": { "distance_cm": 41.2, "squint": 0.93 },
    "window_s": 30
  }
}
```

### `break`

20-20-20 far-look break lifecycle. Phases: `offered` → `started` → `tick` (about 1 Hz) → `verified`, or `skipped` (user sent `skip_break`) / `abandoned` (looked back too early or timed out). `looking_away_s` is verified by the camera, not a timer.

| Field | Type |
| --- | --- |
| `id` | string |
| `phase` | `'offered'\|'started'\|'tick'\|'verified'\|'skipped'\|'abandoned'` |
| `target_s` | number (normally 20) |
| `looking_away_s` | number |
| `streak` | integer, consecutive verified breaks today |

```json
{
  "v": 1, "type": "break", "t": 1767225640000,
  "data": { "id": "b_000012", "phase": "tick", "target_s": 20, "looking_away_s": 12.5, "streak": 3 }
}
```

### `doctrine`

The user's personal care doctrine, compiled by Bedrock from their own eye description. Sent on connect and after every change. Until `approved` is true the agent runs on default rules only.

| Field | Type | Notes |
| --- | --- | --- |
| `version` | integer | Monotonic. `approve_doctrine` must echo it |
| `source_text` | string | The user's description |
| `approved` | boolean | |
| `rules[]` | `{ n: integer, text, origin: 'bedrock'\|'user'\|'proposal'\|'default', status: 'active'\|'pending'\|'rejected', basis }` | `n` is 1-based; `basis` explains why the rule exists |

```json
{
  "v": 1, "type": "doctrine", "t": 1767225600500,
  "data": {
    "version": 3,
    "source_text": "Myopia -3.5 both eyes, early cataract in left eye. Glare bothers me at night.",
    "approved": false,
    "rules": [
      { "n": 1, "text": "Prefer enlarging text over interrupting when distance drops below 30 cm.", "origin": "bedrock", "status": "active", "basis": "Myopia -3.5: sustained near focus under 30 cm drives accommodation strain." },
      { "n": 2, "text": "In dim rooms, suggest dark mode before brightening the screen.", "origin": "bedrock", "status": "active", "basis": "Early cataract: glare from bright screens in dark rooms scatters light." },
      { "n": 3, "text": "Never interrupt during video calls.", "origin": "default", "status": "active", "basis": "Default doctrine." }
    ]
  }
}
```

### `proposal`

A rule change the agent learned from observed moments. Re-sent with a new `status` after `approve_proposal` / `reject_proposal`; an approval is followed by a new `doctrine` with the rule added (`origin: "proposal"`).

| Field | Type |
| --- | --- |
| `id` | string |
| `rule_text` | string |
| `reason` | string |
| `moments[]` | `{ t: epoch_ms, note: string }`, the evidence |
| `status` | `'pending'\|'approved'\|'rejected'` |

```json
{
  "v": 1, "type": "proposal", "t": 1767226200000,
  "data": {
    "id": "p_000004",
    "rule_text": "When reading PDFs after 21:00, start at zoom +1.",
    "reason": "Three late-evening PDF sessions each needed a manual enlarge within 2 minutes.",
    "moments": [
      { "t": 1767139200000, "note": "Squint 0.62 at 24 cm in PDF, dim room, 21:40" },
      { "t": 1767182400000, "note": "Squint 0.66 at 26 cm in PDF, dim room, 22:05" }
    ],
    "status": "pending"
  }
}
```

### `stats`

Today's counters. Sent on connect and about every 10 s.

| Field | Type | Notes |
| --- | --- | --- |
| `day` | string | Local date `YYYY-MM-DD` |
| `under30_min`, `longest_bout_min`, `glasses_off_min` | number | Minutes |
| `breaks_offered`, `breaks_verified`, `streak` | number | |
| `squint_episodes` | number | |
| `adaptations`, `adaptations_worked` | number | Actions and verified-worked actions |
| `decisions`, `decider_p50_ms`, `decider_p95_ms` | number | |
| `face_images_uploaded` | number | Privacy counter. Always 0 in normal use: frames never leave the machine |
| `bedrock_calls`, `bedrock_tokens` | number | Cloud usage |

```json
{
  "v": 1, "type": "stats", "t": 1767225660000,
  "data": {
    "day": "2026-01-01",
    "under30_min": 45.2, "longest_bout_min": 52,
    "breaks_offered": 9, "breaks_verified": 7, "streak": 3,
    "squint_episodes": 14, "glasses_off_min": 38,
    "adaptations": 11, "adaptations_worked": 8,
    "decisions": 1240, "decider_p50_ms": 298, "decider_p95_ms": 611,
    "face_images_uploaded": 0,
    "bedrock_calls": 4, "bedrock_tokens": 6120
  }
}
```

### `report`

Bedrock-written summary, in reply to `request_report`.

| Field | Type |
| --- | --- |
| `id` | string |
| `period` | `'today'\|'week'` |
| `markdown` | string (render as Markdown, sanitized: no raw HTML) |
| `model` | string |
| `generated_at` | epoch ms |

```json
{
  "v": 1, "type": "report", "t": 1767225670000,
  "data": {
    "id": "r_000002",
    "period": "today",
    "markdown": "## Today\n\n- 45 min closer than 30 cm (down from 71 yesterday)\n- 7 of 9 breaks verified",
    "model": "anthropic.claude-sonnet-4",
    "generated_at": 1767225669000
  }
}
```

### `email_draft`

Eye-exam request draft, in reply to `draft_exam_email`. Nothing is ever sent automatically. Status goes `draft` → `pending_confirm` (a `confirm_request` is out) → `opened` (handed to the user's mail app via `mailto:`).

| Field | Type |
| --- | --- |
| `id` | string |
| `subject` | string |
| `body` | string |
| `status` | `'draft'\|'pending_confirm'\|'opened'` |
| `to?` | string \| null (EXTENSION) |

```json
{
  "v": 1, "type": "email_draft", "t": 1767225680000,
  "data": {
    "id": "e_000001",
    "subject": "Request for an eye exam: screen-strain notes from the last 2 weeks",
    "body": "Hello,\n\nI would like to book an eye exam. Attached is a summary of my screen habits...",
    "status": "draft",
    "to": null
  }
}
```

### `confirm_request`

The backend needs explicit user approval for a consequential step (opening the mail draft, a `Confirm`-gated action). The UI shows a modal and answers with the `confirm` command. If the socket drops, the backend treats it as denied.

| Field | Type |
| --- | --- |
| `request_id` | string |
| `title` | string |
| `detail` | string |

```json
{
  "v": 1, "type": "confirm_request", "t": 1767225681000,
  "data": {
    "request_id": "c_000009",
    "title": "Open email draft in your mail app?",
    "detail": "Myrmidon will open a mailto: link. Nothing is sent until you press Send yourself."
  }
}
```

### `toast`

Transient notice.

| Field | Type |
| --- | --- |
| `level` | `'info'\|'success'\|'warning'` |
| `text` | string |

```json
{ "v": 1, "type": "toast", "t": 1767225682000, "data": { "level": "success", "text": "Calibration saved: baseline 55 cm." } }
```

---

## Client to server commands

Shape: `{ "v": 1, "type": "cmd", "name": <name>, "args": { ... }, "t"?: epoch_ms }`. Build with `makeCommand(name, args)`.

| Name | Args | Backend response |
| --- | --- | --- |
| `set_eye_description` | `{ text: string }` | New `doctrine` (higher `version`, `approved: false`) |
| `approve_doctrine` | `{ version: integer }` | `doctrine` with `approved: true`. A stale `version` gets a warning `toast` |
| `approve_proposal` | `{ id: string }` | `proposal` with `status: "approved"`, then updated `doctrine` |
| `reject_proposal` | `{ id: string }` | `proposal` with `status: "rejected"` |
| `start_calibration` | `{ distance_cm: number > 0 }` | `toast` when the baseline is saved; `signals.squint` is relative to the new baseline |
| `request_report` | `{ period: 'today'\|'week' }` | `report` |
| `draft_exam_email` | `{}` | `email_draft` |
| `confirm` | `{ request_id: string, approve: boolean }` | Whatever the confirmed step produces (e.g. `email_draft` with `status: "opened"`) |
| `pause_camera` | `{ paused: boolean }` | `hello` with `camera.status` `paused` / `on` |
| `skip_break` | `{ id: string }` | `break` with `phase: "skipped"` |

```json
{ "v": 1, "type": "cmd", "name": "set_eye_description", "args": { "text": "Myopia -3.5 both eyes, early cataract in left eye. Glare bothers me at night." } }
{ "v": 1, "type": "cmd", "name": "approve_doctrine", "args": { "version": 3 } }
{ "v": 1, "type": "cmd", "name": "approve_proposal", "args": { "id": "p_000004" } }
{ "v": 1, "type": "cmd", "name": "reject_proposal", "args": { "id": "p_000004" } }
{ "v": 1, "type": "cmd", "name": "start_calibration", "args": { "distance_cm": 55 } }
{ "v": 1, "type": "cmd", "name": "request_report", "args": { "period": "week" } }
{ "v": 1, "type": "cmd", "name": "draft_exam_email", "args": {} }
{ "v": 1, "type": "cmd", "name": "confirm", "args": { "request_id": "c_000009", "approve": true } }
{ "v": 1, "type": "cmd", "name": "pause_camera", "args": { "paused": true } }
{ "v": 1, "type": "cmd", "name": "skip_break", "args": { "id": "b_000012" } }
```

---

## Worked flows

Adapt and verify (the core loop):

1. `signals` at 27 cm, squint 0.71, dim room, PDF.
2. `decision` `d_000142`: `next_action.choice = enlarge_text`, `interrupt_ok.p = 0.78`, `policy = act`, `rule_ref = "rule 2"`.
3. `action` `a_000057` on `d_000142`: `InterruptGate` proceeds, `status = done`, `app.zoom_step` becomes 1 in later `signals`.
4. 30 s later, `verification` for `a_000057`: distance 27.4 → 41.2 cm, squint 0.71 → 0.93, `outcome = worked`. `stats.adaptations_worked` increments.

Ask before acting:

1. `decision` with `policy = ask`.
2. `action` with `tool = ask_user`, `gate = { name: "Confirm", verdict: "pending", p: null }`, `status = pending_confirm`.
3. `confirm_request` `c_...`; user answers `confirm { request_id, approve }`.
4. `action` re-sent with the same `id`: `verdict` `proceed`/`deny`, `status` `done`/`denied`.

Doctrine onboarding:

1. UI sends `set_eye_description`.
2. Backend replies with `doctrine` (`version` n, `approved: false`).
3. UI shows the rules with their `basis`; user taps approve; UI sends `approve_doctrine { version: n }`.
4. Backend replies with `doctrine` (`approved: true`).

Exam email:

1. `draft_exam_email {}` → `email_draft` (`draft`).
2. Backend sends `confirm_request`, `email_draft` (`pending_confirm`).
3. `confirm { approve: true }` → `email_draft` (`opened`); the backend opens the `mailto:` link. `approve: false` returns it to `draft`.

## Validating

- In the UI: `parseServerMessage(frame)` returns `{ ok: true, event }` or `{ ok: false, reason }` where `reason` is `invalid_json`, `not_envelope`, `bad_version`, `unknown_type` or `invalid_data`. It never throws.
- In the backend or tests: validate frames against `web/contract.schema.json` (`#/$defs/ServerEvent`, `#/$defs/ClientCommand`). `EXAMPLE_EVENTS` and `EXAMPLE_COMMANDS` in `contract.ts` are the examples in this document and pass both the schema and the guards.
