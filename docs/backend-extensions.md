# Backend extensions to the UI contract

The backend sends a few optional fields beyond `docs/ui-contract.md`. They follow the contract's compatibility rules: receivers ignore unknown fields, and nothing here changes a required field. The web UI may render them. `docs/ui-contract.md` and `web/` are unchanged.

## `decision`

| Field | Type | Meaning |
|---|---|---|
| `answers.rules[]` | `{ n, tool, p, state, escalated }` | One entry per candidate rule in priority order. `p` is the Decider's P(rule applies), or `null` if missing. `state` is `fires` (p >= 0.65), `unsure` (between) or `clear` (p <= 0.35). `escalated` is `true`/`false` when Nova Lite judged an unsure rule, `null` otherwise |
| `reason` | string | One line from the policy, e.g. `rule 1 fires (p=0.96)` or `rule 4 unsure (p=0.42) and escalation unavailable: fail quiet` |
| `skipped[]` | `{ n, tool, why }` | Rules that were not asked this tick, e.g. `cooldown`, `zoom unavailable or at cap`, `demoted in this app`, `a break is running` |
| `escalation` | `{ model, latency_ms, verdicts, skipped }` | Present when unsure rules went to Amazon Nova Lite (text only). `verdicts` maps rule number (string) to `true`/`false`/`null`. `skipped` explains a `null` (rate limited, budget, timeout, error) |

`answers.next_action.probs` is normalised over `{tool: max p}` plus `none = prod(1 - p)`. The choice comes from code (priority order plus the confidence policy), so `choice` is not always the highest probability. `answers.strain` is counted in code from four signs (squinting, too close, break due, low blink rate), so its `probs` are one-hot.

`source: "fallback"` means the Decider was down or slower than 4 s. The policy is then always `quiet`, and `answers.interrupt_ok.p` is 0.

## `break`

| Field | Type | Meaning |
|---|---|---|
| `face_absent_s` | number | Seconds of the break with no face visible (the user walked away). They count as looking away |

## `hello`

- `decider.model` is `"FAKE oracle (tests/demo)"` with `--fake-decider`. That mode never presents itself as the real model.
- `camera.status` is `off` in replay modes, because the camera is not used there. It is `paused` while the replay is paused.
