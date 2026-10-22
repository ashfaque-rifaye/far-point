# REUSABLE DECISION PATTERN: Reflex Gate

Reflex Gate turns a small rulebook into fast local decisions with Strands Decider 2B, then runs the chosen tool through a Strands Agent, where interventions can stop it. Far Point uses it for eye habits. Nothing in this package knows about eyes: it imports only `strands`, `pydantic` and the standard library. `examples/posture_agent.py` applies it to posture.

## What it does

1. Code measures the world and renders the facts in words. It also does the arithmetic: a line reads "27 cm, closer than 30 cm for 8 s (limit 5 s): too close", not "27 cm".
2. Each rule in a numbered, priority-ordered rulebook becomes one `noul` question ("does rule N apply right now?"). One Decider request asks every candidate rule plus `interrupt_ok` over the same state.
3. Code applies the priority order and a confidence policy (below) and picks at most one tool. The Decider judges which rules apply; the order picks the tool.
4. The tool runs as `agent.tool.<name>(...)`. Strands interventions run on that call. `InterruptGate` denies interruptive tools at a bad moment, and `ConfirmGate` puts a human answer in front of persistent or outbound tools.

Why per-rule nouls: in Far Point's Phase 1 spike, a single 9-way `choice` question agreed with the rulebook on 68.1% of held-out states, and it mostly lost on the priority order. The same spike scored the v2 `interrupt_ok` noul at 100% (`eval/SPIKE_RESULTS.md`). Asking one yes/no question per rule and resolving the order in code plays to what the model did well.

## Typed questions and options

`rule_question(Rule(n=1, tool="enlarge_text", text=..., when_true=..., when_false=...))` produces:

```json
{
  "type": "noul",
  "instructions": "Does rule 1 apply right now? Rule 1: The Viewing distance line says enlarging needed.",
  "criteria": {
    "true": "the Viewing distance line says 'enlarging needed'",
    "false": "the Viewing distance line says 'no enlarging needed', 'no enlarging needed yet', 'no face visible' or 'this app has no zoom control'"
  }
}
```

The rendered line it reads is written by code, for example `- Viewing distance: 27 cm, under 30 cm for 8 s (limit 5 s): too close, enlarging needed.` Two wording lessons came from probing the real Decider while building Far Point (single requests, not a held-out eval):

- End each line with one verdict phrase, in the form "X needed" / "no X needed". For the brightness rule, "dimming needed" / "no change needed" scored p 0.97 / 0.10. The descriptive pair "high for a dark room" / "suits the room" scored 0.95 / 0.43, so the no-change case sat in the unsure band.
- Fold any AND that a rule needs into one line in code. A rule that needed "too close" on one line AND "zoom control available" on another left the no-change states at p 0.37-0.69.

`INTERRUPT_OK` (the v2 wording from the spike, copied verbatim):

```json
{
  "type": "noul",
  "instructions": "Read the Activity line. Is it OK to interrupt the user with a prompt right now?",
  "criteria": {
    "true": "Activity says idle, between tasks, or just switched windows",
    "false": "Activity says video call, presenting or screen sharing, typing in a burst, or fullscreen video"
  }
}
```

`build_questions(rules)` returns `{"rule_1": ..., "rule_2": ..., "interrupt_ok": ...}`. The option set is the tools named by the rules, plus `none`. `select()` reports it as a contract-shaped `next_action`: `probs` is normalised over `{tool: max p}` plus `none = prod(1 - p)`.

## Thresholds and why

| Threshold | Default | Meaning |
|---|---|---|
| `fire_p` | 0.65 | A rule fires at p >= 0.65 |
| `clear_p` | 0.35 | A rule is clear at p <= 0.35; between the two it is UNSURE |
| `interrupt_p` | 0.5 | `InterruptGate` proceeds at p >= 0.5 |
| `ask_cooldown_s` | 1800 | The ask tool runs at most once per 30 min |

The policy walks the rules in priority order and takes the first one that fires, unless a higher-priority rule is unsure. Those unsure rules go to `escalate` (Far Point uses Amazon Nova Lite on the same text state). If escalation is off, fails or gives no verdict, the policy stays quiet and the caller logs the unsure moment ("fail quiet"). A wrong interruption costs more than a missed one, so the 0.35-0.65 band is wide on purpose. The values are fixed before measurement, not tuned on the eval sets.

## Wiring

```python
from strands import Agent
from patterns.reflex_gate import (ConfirmGate, DeciderHttpClient, InterruptGate,
                                  Rule, build_questions, select)

decider = DeciderHttpClient("http://127.0.0.1:8099/v1/systemone")   # one process-wide lock inside
gate = InterruptGate(decider, state_provider=lambda: state_text, interruptive_tools={"stand_break"})
confirm = ConfirmGate({"save_profile": lambda a: "Save this profile?"}, ask_human=my_ui_prompt)
agent = Agent(model=any_model, tools=[posture_nudge, stand_break, save_profile],
              interventions=[gate, confirm], record_direct_tool_call=False, callback_handler=None)

resp = decider.ask(state_text, build_questions(rules))         # one request: N rules + interrupt_ok
sel = select(rules, resp["answers"], escalate=None)            # code applies the order
if sel.tool:
    gate.prime(sel.interrupt_p)                                # reuse the batched interrupt_ok answer
    result = getattr(agent.tool, sel.tool)()                   # interventions run here
    denied = result["status"] == "error" and result["content"][0]["text"].startswith("DENIED:")
```

The agent's model is never invoked on this path. `tests/test_gate_direct_call.py` proves it with a model that raises on any call.

Direct calls pass through interventions. I checked the installed strands-agents 1.62.0 source: `agent.tool.<name>()` (`strands/tools/_caller.py`) runs `ToolExecutor._stream`, which fires `BeforeToolCallEvent` (`strands/tools/executors/_executor.py`), and `InterventionRegistry` hooks that event. A denied call returns a ToolResult with status `error` and text `DENIED: ...` (or `CONFIRMATION_FAILED: ...` for a failed Confirm). The test pins this, so the fallback dispatcher the plan allowed for was not needed. `Confirm` without a `response` raises "cannot raise interrupt in direct tool call", so `ConfirmGate` gets the human answer first and returns `Confirm(prompt, response=answer)`. That uses Strands' own Confirm evaluation and works the same in model-driven calls.

References: the official Decider + Strands example, https://github.com/strands-labs/strands-decider/tree/main/examples/strands, and the interventions docs, https://strandsagents.com/docs/integrations/interventions/overview/.

## Testing without a GPU or AWS

- `FakeDecider(fn)` returns the server's response shape. `fn(state, name, question) -> p`. `oracle(predicate_for, interrupt_ok)` builds a crisp fn from code predicates.
- `ScriptedModel(script)` is a `strands.models.Model` that replays `{"tool": ..., "input": ...}` / `{"text": ...}` turns as Bedrock-style stream events and records every request in `.calls`. `ScriptedModel(fail_if_called=True)` raises on any call. `contains_image(model.calls)` checks that no request carried an image.
- Run: `python -m pytest -q patterns/reflex_gate/tests`.

## Example

`python -m patterns.reflex_gate.examples.posture_agent --fake` runs offline. Drop `--fake` to use a Decider on 127.0.0.1:8099. It prints the selection and the gate verdict for 4 canned states. The meeting state is denied by `InterruptGate`.

## Measured (Far Point, `eval/S3_RESULTS.md`)

Preregistered, held-out seed 4, 72 synthetic states, thresholds fixed at 0.35 / 0.65:

- One 9-way choice (Phase 1): 68.1%. Per-rule nouls + code priority: **87.5%** end to end. Every miss was the policy failing quiet on an unsure higher-priority rule, not a wrong action.
- With Amazon Nova Lite on the unsure rules: 100%. 1.7% of nouls were unsure, and 9 of 72 states were escalated.
- The same decomposition over the old text, which describes measurements but leaves conditions for the model to combine: 30.6%. The verdict-style rendering carries most of the gain.
- 9 questions per request: p50 458-574 ms on an RTX 4060 laptop.

## Limits

- Phase 1 baseline: one 9-way choice agreed with the rulebook on 68.1% of held-out states.
- With verdict-style rendering, code computes each rule's conditions and the Decider reads the verdict. That is the point of the pattern, but it means rules that combine lines in new ways (for example ones a language model writes) are less reliable than the S3 number.
- `interrupt_ok` scored 83.3% over the S3 rendering, with misses on typing bursts and video calls. Far Point now appends code's activity verdict to the Activity line. Probes improved, but S3 did not measure it.
- Wording matters. In the spike, rewording one question moved one label from 100% to 12%. Keep criteria explicit, quote the rendered line the rule should read, and do the arithmetic in code.
- Every Decider call in a process goes through one lock (`client._LOCK`), because overlapping requests can get each other's answers (strands-decider issue #17). Throughput is one request at a time.
- `DeciderHttpClient` refuses to send images to any host other than localhost.

## License

Apache-2.0, like the rest of the repository.
