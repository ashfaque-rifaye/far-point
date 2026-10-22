"""The reflex loop: MEASURE -> DECIDE -> ACT -> VERIFY, every `period_s` seconds.

MEASURE  facts from the SignalTracker plus actuator read-back, rendered in words by code.
DECIDE   one local Decider request: one noul per feasible rule + interrupt_ok. Code applies
         the priority order (patterns.reflex_gate.select); unsure rules may go to Nova Lite.
ACT      the chosen tool runs via agent.tool.<name>(), behind InterruptGate / ConfirmGate.
VERIFY   the Verifier checks what the camera measures afterwards.

Fail quiet: if the Decider is down or slow, publish a `fallback` decision and do nothing.
"""
from __future__ import annotations

import itertools
import logging
import threading
import time

from patterns.reflex_gate import build_questions, select

from .act import ZOOM_CAP_DOWN, ZOOM_CAP_UP
from .agent import INTERRUPTIVE, call_tool
from .doctrine import DEFAULT_ARGS, DoctrineRule
from .facts import Facts, render_state, strain
from .vision import CONTRACT_KEYS, FRESH_S, S2_STATE, tri, vision_questions

log = logging.getLogger("farpoint.loop")

COOLDOWN_S = 60.0
BREAK_COOLDOWN_S = 600.0
RETRY_BACKOFF_S = 30.0


class ReflexLoop:
    def __init__(self, *, tracker, doctrine_store, decider, agent, interrupt_gate, verifier, prefs, moments, stats,
                 bus, actuators, breaks, tool_ctx, thresholds, escalator=None, clock=time.time, period_s=2.5,
                 decider_timeout_s=4.0, vision=False, image_provider=None):
        self.tracker = tracker
        self.store = doctrine_store
        self.decider = decider
        self.agent = agent
        self.gate = interrupt_gate
        self.verifier = verifier
        self.prefs = prefs
        self.moments = moments
        self.stats = stats
        self.bus = bus
        self.act = actuators
        self.breaks = breaks
        self.ctx = tool_ctx
        self.thresholds = thresholds
        self.escalator = escalator
        self.clock = clock
        self.period_s = period_s
        self.decider_timeout_s = decider_timeout_s
        self.vision = vision
        self.image_provider = image_provider  # vision mode: () -> base64 JPEG of the latest webcam frame
        self.last_vision: dict | None = None
        self.paused = False
        self.current_facts = Facts()
        self.current_state_text = ""
        self.last_done: dict[str, float] = {}
        self.last_retry: dict[str, float] = {}
        self.last_ask_t: float | None = None
        self.pending_ask: str | None = None
        self.actions: dict[str, dict] = {}
        self.decisions = 0
        self._demoted_logged: set[tuple[str, str]] = set()
        self._moment_seen: dict[tuple, float] = {}
        self._d_ids = itertools.count(1)
        self._a_ids = itertools.count(1)
        self._next_t: float | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._tick_lock = threading.Lock()
        tool_ctx.on_ask_answer = self._on_ask_answer

    # ---- MEASURE ------------------------------------------------------------------------
    def measure(self) -> Facts:
        f = self.tracker.snapshot()
        st = self.act.state()
        f.zoom_available = bool(st["zoom_available"])
        f.zoom_step = int(st["zoom_step"])
        f.theme = st["theme"]
        f.brightness_pct = st["brightness_pct"]
        f.glasses_prescribed = self.store.active.profile.glasses_for_screen
        now = self.clock()
        f.local_time = time.strftime("%H:%M", time.localtime(now))
        f.vision = bool(self.vision)
        f.glasses_on = self.vision_glasses_on(now)
        return f

    # ---- vision mode (off unless S2 passed; see farpoint/vision.py) ---------------------
    def vision_glasses_on(self, now: float | None = None) -> bool | None:
        lv = self.last_vision
        now = self.clock() if now is None else now
        if not self.vision or lv is None or now - lv["t"] > FRESH_S:
            return None
        return tri(lv["p"]["glasses_on"], self.thresholds.fire_p, self.thresholds.clear_p)

    def _vision_pass(self, now: float) -> dict | None:
        """One image request: the S2-measured state, questions and a single webcam frame, to
        the LOCAL Decider. It runs before the text request so this tick's state can use it."""
        if not self.vision or self.image_provider is None:
            return None
        frame = self.image_provider()
        if not frame:
            return None
        t0 = time.perf_counter()
        try:
            resp = self.decider.ask(S2_STATE, vision_questions(), images=[frame], timeout=self.decider_timeout_s)
        except Exception as e:  # noqa: BLE001 - the text decision still runs
            log.warning("vision request failed: %s: %s", type(e).__name__, e)
            return None
        answers = resp.get("answers", {})
        probs = {CONTRACT_KEYS[k]: round(float((answers.get(k) or {}).get("noul", 0.0)), 4) for k in CONTRACT_KEYS}
        latency = float(resp.get("latency_ms") or (time.perf_counter() - t0) * 1000)
        self.last_vision = {"t": now, "p": probs, "latency_ms": latency}
        self.tracker.set_vision(now, probs["looking_far"],
                                tri(probs["glasses_on"], self.thresholds.fire_p, self.thresholds.clear_p))
        return self.last_vision

    def feasible(self, rule: DoctrineRule, f: Facts, now: float) -> tuple[bool, str]:
        tool = rule.tool
        cooldown = BREAK_COOLDOWN_S if tool == "far_look_break" else COOLDOWN_S
        if tool in self.last_done and now - self.last_done[tool] < cooldown:
            return False, "cooldown"
        if tool in self.last_retry and now - self.last_retry[tool] < RETRY_BACKOFF_S:
            return False, "backoff after a deny or failure"
        if self.prefs.demoted(tool, f.app_category):
            key = (tool, f.app_category)
            if key not in self._demoted_logged:
                self._demoted_logged.add(key)
                self.moments.log("demoted", f"{tool} skipped in {f.app_category}: it rarely helped there",
                                 counts=self.prefs.counts(tool, f.app_category))
            return False, "demoted in this app"
        if tool == "enlarge_text":
            return (f.zoom_available and f.zoom_step < ZOOM_CAP_UP), "zoom unavailable or at cap"
        if tool == "reduce_text":
            return (f.zoom_available and f.zoom_step > ZOOM_CAP_DOWN), "zoom unavailable or at cap"
        if tool in ("dim_screen", "brighten_screen"):
            return f.brightness_pct is not None, "brightness not adjustable"
        if tool == "dark_mode":
            want_dark = bool(rule.args.get("on", True))
            ok = self.act.theme.available() and (f.theme == "light" if want_dark else f.theme == "dark")
            return ok, "theme already set"
        if tool == "far_look_break":
            return not self.breaks.is_active(), "a break is running"
        if tool == "glasses_reminder":
            return self.act.overlay.available(), "no overlay"
        if tool == "ask_user":
            if self.pending_ask is not None:
                return False, "a question is already pending"
            ok = self.last_ask_t is None or now - self.last_ask_t >= self.thresholds.ask_cooldown_s
            return ok, "asked recently"
        return True, ""

    # ---- one pass ---------------------------------------------------------------------
    def tick(self) -> dict | None:
        with self._tick_lock:
            if self.paused:
                return None
            return self._tick()

    def _tick(self) -> dict:
        now = self.clock()
        doctrine = self.store.active
        self.tracker.set_limits(doctrine.limits)
        vis = self._vision_pass(now)
        f = self.measure()
        state_text = render_state(f, doctrine)
        self.current_facts, self.current_state_text = f, state_text
        by_n = {r.n: r for r in doctrine.active_rules()}
        candidates, skipped = [], []
        for r in doctrine.to_pattern_rules():
            ok, why = self.feasible(by_n[r.n], f, now)
            if ok:
                candidates.append(r)
            else:
                skipped.append({"n": r.n, "tool": r.tool, "why": why})
        questions = build_questions(candidates)  # text only: images go in the separate vision request
        decision_id = f"d_{next(self._d_ids):06d}"
        st = strain(f, doctrine.limits)
        strain_out = {"level": st["level"], "expected": st["expected"], "probs": st["probs"]}

        t0 = time.perf_counter()
        try:
            resp = self.decider.ask(state_text, questions, timeout=self.decider_timeout_s)
            answers = resp["answers"]
        except Exception as e:  # noqa: BLE001 - Decider down/slow: fail quiet
            latency = (time.perf_counter() - t0) * 1000
            decision = {
                "id": decision_id, "latency_ms": round(latency, 1), "source": "fallback", "state_text": state_text,
                "answers": {"next_action": {"choice": "none", "confidence": 1.0, "probs": {"none": 1.0}},
                            "strain": strain_out, "interrupt_ok": {"p": 0.0}},
                "policy": "quiet",
                "reason": f"Decider unavailable ({type(e).__name__}): fail quiet, no action",
            }
            if vis is not None:
                decision["answers"]["vision"] = dict(vis["p"])
                decision["vision_latency_ms"] = round(vis["latency_ms"], 1)
            self.bus.publish("decision", decision)
            self.decisions += 1
            return decision
        latency = float(resp.get("latency_ms") or (time.perf_counter() - t0) * 1000)
        self.stats.record_decider_latency(latency)

        decider_p = {r.n: (answers.get(f"rule_{r.n}") or {}).get("noul") for r in candidates}
        escalate = None
        if self.escalator is not None:
            def escalate(rules):
                return self.escalator(state_text, rules, {n: decider_p.get(n) for n in (r.n for r in rules)})
        sel = select(candidates, answers, self.thresholds, escalate=escalate, now=now, last_ask_t=self.last_ask_t)
        if sel.policy == "quiet" and sel.unsure and self.escalator is None:
            self._moment_once("unsure", tuple(sel.unsure), now, sel.reason, rules=sel.unsure,
                              p={str(n): decider_p.get(n) for n in sel.unsure})

        io_p = sel.interrupt_p if sel.interrupt_p is not None else 0.0
        decision = {
            "id": decision_id,
            "latency_ms": round(latency, 1),
            "source": "decider",
            "state_text": state_text,
            "answers": {
                "next_action": sel.next_action,
                "strain": strain_out,
                "interrupt_ok": {"p": round(io_p, 4)},
                "rules": [{**v.to_dict(), "p": None if v.p is None else round(v.p, 4)} for v in sel.verdicts],
            },
            "policy": sel.policy,
            "reason": sel.reason,
            "skipped": skipped,
        }
        if vis is not None:
            decision["answers"]["vision"] = dict(vis["p"])
            decision["vision_latency_ms"] = round(vis["latency_ms"], 1)
        if sel.rule_n is not None:
            decision["rule_ref"] = f"rule {sel.rule_n}"
        if sel.escalation is not None and self.escalator is not None:
            last = getattr(self.escalator, "last", None) or {}
            decision["escalation"] = {"model": getattr(self.escalator, "model_id", "nova-lite"),
                                      "latency_ms": sel.escalation["latency_ms"],
                                      "verdicts": sel.escalation["verdicts"],
                                      "skipped": last.get("skipped")}
        self.bus.publish("decision", decision)
        self.decisions += 1

        if sel.policy in ("act", "ask") and sel.tool and sel.rule_n is not None:
            self._act(decision_id, by_n[sel.rule_n], sel.interrupt_p, f, now)
        return decision

    def _moment_once(self, kind: str, key, now: float, note: str, **numbers) -> None:
        """Log a moment unless the same one was logged in the last 60 s (one per episode)."""
        last = self._moment_seen.get((kind, key))
        if last is not None and now - last < 60.0:
            self._moment_seen[(kind, key)] = now
            return
        self._moment_seen[(kind, key)] = now
        self.moments.log(kind, note, **numbers)

    # ---- ACT + VERIFY -----------------------------------------------------------------
    def _act(self, decision_id: str, rule: DoctrineRule, interrupt_p, f: Facts, now: float) -> dict:
        tool = rule.tool
        action_id = f"a_{next(self._a_ids):06d}"
        args = dict(rule.args) if rule.args else dict(DEFAULT_ARGS.get(tool, {}))
        self.ctx.current = {"action_id": action_id, "decision_id": decision_id, "category": f.app_category}
        before = self.verifier.measure()
        if tool in INTERRUPTIVE:
            self.gate.prime(interrupt_p)
        out = call_tool(self.agent, tool, args, self.gate)
        data = {"id": action_id, "decision_id": decision_id, "tool": tool, "args": args, "gate": out.gate,
                "status": out.status, "message": out.message}
        self.actions[action_id] = data
        self.bus.publish("action", data)
        if out.status == "done":
            self.last_done[tool] = now
            self.stats.inc("adaptations")
            if tool not in ("far_look_break", "reset"):
                self.verifier.watch(action_id, tool, before, f.app_category)
        elif out.status == "pending_confirm":
            self.last_ask_t = now
            self.pending_ask = action_id
            self.moments.log("ask", out.message, rule=rule.n)
        else:
            self.last_retry[tool] = now
            if out.status == "denied":
                self.moments.log("denied", f"{tool}: {out.message}", rule=rule.n, interrupt_p=interrupt_p,
                                 category=f.app_category)
        return data

    def _on_ask_answer(self, action_id: str, approve: bool) -> None:
        data = self.actions.get(action_id)
        if self.pending_ask == action_id:
            self.pending_ask = None
        if data is None:
            return
        data = {**data, "gate": {"name": "Confirm", "verdict": "proceed" if approve else "deny", "p": None},
                "status": "done" if approve else "denied",
                "message": "You said yes: break started." if approve else "You said not now."}
        self.actions[action_id] = data
        self.bus.publish("action", data)

    # ---- scheduling ---------------------------------------------------------------------
    def on_time(self, t: float) -> None:
        """Inline scheduling (replay): tick when `period_s` of trace time has passed."""
        if self._next_t is None:
            self._next_t = t + self.period_s
            return
        if t >= self._next_t:
            self._next_t = t + self.period_s
            try:
                self.tick()
            except Exception:  # noqa: BLE001
                log.exception("tick failed")

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="farpoint-loop", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.wait(self.period_s):
            try:
                self.tick()
            except Exception:  # noqa: BLE001
                log.exception("tick failed")

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(10)
