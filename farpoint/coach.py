"""The Coach: Amazon Nova (Bedrock) through a Strands Agent. Words and numbers only.

- compile_doctrine: the user's own eye description -> a draft rulebook (approved in the UI).
- report: numbers-only reports, prefixed "Behavioral observations, not a diagnosis."
- review_moments: proposes rule changes from logged moments; a human approves each one.
- draft_exam: drafts an eye-exam email. It is opened in the user's mail app only after a
  confirmation, and never sent by Far Point.

Persistent or outbound tools (`adopt_doctrine`, `open_exam_email`) sit behind a
ConfirmGate. The Coach never receives images.
"""
from __future__ import annotations

import itertools
import json
import logging
import os
import re
import threading
import time
import urllib.parse
from concurrent.futures import Future, ThreadPoolExecutor

from pydantic import ValidationError
from strands import Agent, tool

from patterns.reflex_gate import ConfirmGate, ScriptedModel

from .doctrine import TOOLS, DoctrineRule, Limits, Profile, StaleVersion
from .facts import FACT_LINE_GUIDE

log = logging.getLogger("farpoint.coach")

COACH_MODEL = os.environ.get("FARPOINT_COACH_MODEL", "us.amazon.nova-lite-v1:0")
REGION = os.environ.get("AWS_REGION", "us-east-1")
DISCLAIMER = "> Behavioral observations, not a diagnosis."
MAX_DOCTRINE_ATTEMPTS = 3  # first try + 2 retries
REVIEW_EVERY_S = 15 * 60
REVIEW_MIN_MOMENTS = 3
RED_FLAGS = ("sudden loss", "sudden vision", "lost vision", "lost my vision", "vision loss", "flash", "curtain",
             "shadow over", "eye pain", "painful eye", "pain in my eye", "double vision", "seeing double")

SYSTEM_PROMPT = f"""You are the coach inside Far Point, a screen-habits assistant that runs on the user's laptop.
Behavioral observations, not a diagnosis: you describe habits and numbers. Never diagnose, never name a
disease the user did not name, never give treatment or prescription advice, and never claim that Far Point
treats or prevents any condition. When something sounds urgent, say to contact an eye doctor.

Far Point's local loop renders the measured state as these exact lines (code computes every number):
{FACT_LINE_GUIDE}

Rules you write may only reference those lines and their verdict words. Each rule maps to exactly one tool:
{", ".join(t for t in TOOLS if t != "reset")}.
Lower rule numbers win when several rules apply. Keep ask_user last.
Numeric limits are knobs with safe ranges (code clamps them): near_cm, near_s, bout_cm, bout_min, bout_reset_s,
relaxed_cm, relaxed_min, squint_ratio, squint_s, lean_in_cm, low_blink_per_min, dim_pct_high, bright_pct_low.
Default thresholds come from the Clouclip pilot (children's cohort): under 30 cm for more than 5 s, or under
60 cm for more than 45 min, counts as unhealthy near work."""

DOCTRINE_TASK = """The user described their eyes in their own words:
\"\"\"{text}\"\"\"

Personalise Far Point's default rulebook (JSON below) for this user:
- Keep the default rules that make sense for this user. Copy them exactly, including when_true / when_false.
- Add at most 3 new rules for what the user described. Each must quote one fact line's verdict phrase.
- Put numbers only in limits (for example a lower bout_min for more frequent breaks). Never put numbers in
  rule text. Only include the limits you change.
- profile.glasses_for_screen: "yes" only if the user says they wear glasses for screen work, "no" if they
  say they do not, else "unknown". profile.conditions: short phrases copied from the user's words.
- basis: quote the user's words that motivated the rule, or "Default doctrine".
- No duplicate rules. ask_user stays last.

Default rulebook:
{defaults}

Call write_doctrine exactly once with profile, limits and rules (highest priority first). Then reply with one
short sentence. Do not give medical advice."""

REPORT_TASK = """Write a short report for {period} for the user. Call get_today_stats (and summarize_period
with days=7 for a week). Use only the numbers the tools return: minutes closer than 30 cm, longest near-work
bout, breaks offered and verified, squint episodes, adaptations that worked. 4 to 8 bullet points of plain
Markdown, no HTML, no tables, no diagnosis, no medical advice. End with one practical habit tip."""

REVIEW_TASK = """These moments were logged by the local loop (numbers and short notes):
{moments}

If a pattern repeats at least 3 times, call propose_rule once with a rule that would have helped, citing the
moment ids. If there is no clear pattern, reply "no proposal". A human approves every proposal."""

EMAIL_TASK = """Draft a short email the user can send to an eye clinic to request an eye exam. Call
summarize_period with days=14 and include only those numbers as behavioral observations (minutes closer than
30 cm, longest bout, squint episodes, breaks verified). Say plainly that these are screen-habit observations
from a laptop camera, not a diagnosis. No medical claims. Call draft_exam_request(subject, body) once."""


def make_agent(system_prompt: str = SYSTEM_PROMPT, model=None, tools=None, interventions=None, max_tokens: int = 1500):
    if model is None:
        from strands.models import BedrockModel
        model = BedrockModel(model_id=COACH_MODEL, region_name=REGION, max_tokens=max_tokens, temperature=0.3)
    return Agent(model=model, system_prompt=system_prompt, tools=tools or [], interventions=interventions or [],
                 callback_handler=None, name="farpoint-coach")


MAX_RULES = 9  # 9 rule nouls + interrupt_ok keeps one Decider request under ~0.5 s here


def red_flags(text: str) -> list[str]:
    t = text.lower()
    return [k for k in RED_FLAGS if k in t]


def tidy_rules(rules: list[DoctrineRule]) -> list[DoctrineRule]:
    """Code-side cleanup of model output: drop duplicates, keep ask_user last, cap the count."""
    seen, out = set(), []
    for r in sorted(rules, key=lambda r: r.n):
        key = (r.tool, " ".join(r.when_true.lower().split()))
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    ordered = [r for r in out if r.tool != "ask_user"] + [r for r in out if r.tool == "ask_user"]
    if len(ordered) > MAX_RULES:
        asks = [r for r in ordered if r.tool == "ask_user"][:1]
        ordered = [r for r in ordered if r.tool != "ask_user"][: MAX_RULES - len(asks)] + asks
    return [r.model_copy(update={"n": i}) for i, r in enumerate(ordered, 1)]


def default_rules_json() -> str:
    from .doctrine import default_doctrine
    keep = ("n", "text", "tool", "args", "when_true", "when_false", "basis")
    return json.dumps([{k: v for k, v in r.model_dump().items() if k in keep}
                       for r in default_doctrine().rules], indent=1)


def strip_html(md: str) -> str:
    return re.sub(r"<[^>]{1,200}>", "", md)


def _text_of(result) -> str:
    return " ".join(c.get("text", "") for c in result.get("content", []) if "text" in c)


class Coach:
    def __init__(self, bus, doctrine_store, stats, moments, broker, model_factory=None, enabled: bool = True,
                 startfile=None, clock=time.time, model_id: str = COACH_MODEL):
        self.bus = bus
        self.store = doctrine_store
        self.stats = stats
        self.moments = moments
        self.broker = broker
        self.model_factory = model_factory
        self.enabled = enabled
        self.startfile = startfile or getattr(os, "startfile", None)
        self.clock = clock
        self.model_id = model_id
        self.proposals: dict[str, dict] = {}
        self.drafts: dict[str, dict] = {}
        self._p_ids = itertools.count(1)
        self._e_ids = itertools.count(1)
        self._r_ids = itertools.count(1)
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="farpoint-coach")
        self._lock = threading.Lock()
        self._source_text = ""
        self._doctrine_attempts = 0
        self._doctrine_saved = None
        self._last_review = clock()
        self._last_trend_email: float | None = None
        self.gate = ConfirmGate({
            "adopt_doctrine": lambda a: f"Adopt rulebook version {a.get('version')}? Far Point follows it from the next decision.",
            "open_exam_email": lambda a: "Open the eye-exam email draft in your mail app? Nothing is sent until you press Send yourself.",
        }, self._ask_human)
        self.tools = self._build_tools()
        # Direct tool calls (UI approvals) never invoke a model.
        self.direct = make_agent(model=ScriptedModel(fail_if_called=True), tools=self.tools, interventions=[self.gate])

    # ---- plumbing -------------------------------------------------------------------------
    def _model(self):
        if self.model_factory is not None:
            return self.model_factory()
        from strands.models import BedrockModel
        return BedrockModel(model_id=self.model_id, region_name=REGION, max_tokens=1500, temperature=0.3)

    def _run_agent(self, prompt: str):
        agent = make_agent(model=self._model(), tools=self.tools, interventions=[self.gate])
        result = agent(prompt)
        usage = result.metrics.accumulated_usage or {}
        self.stats.record_bedrock(max(1, result.metrics.cycle_count), int(usage.get("totalTokens", 0)), who="coach",
                                  model=self.model_id, input_tokens=int(usage.get("inputTokens", 0)),
                                  output_tokens=int(usage.get("outputTokens", 0)))
        return result

    def submit(self, fn, *args) -> Future:
        def wrapped():
            try:
                return fn(*args)
            except Exception as e:  # noqa: BLE001 - surface to the UI, never crash
                log.exception("coach task failed")
                self.bus.toast("warning", f"Coach error: {type(e).__name__}. Nothing was changed.")
                return None
        return self._pool.submit(wrapped)

    def _off(self) -> bool:
        if not self.enabled:
            self.bus.toast("warning", "Coach not available: Bedrock is off (no credentials or --no-bedrock).")
            return True
        return False

    def _ask_human(self, tool_name: str, prompt: str, args: dict) -> bool:
        key = {"adopt_doctrine": f"doctrine:{args.get('version')}",
               "open_exam_email": f"email:{args.get('draft_id')}"}.get(tool_name, tool_name)
        if self.broker.consume(key):
            return True
        title = "Adopt this rulebook?" if tool_name == "adopt_doctrine" else "Open email draft in your mail app?"
        return self.broker.request(title, prompt, timeout_s=120)

    # ---- tools ------------------------------------------------------------------------------
    def _build_tools(self) -> list:
        coach = self

        @tool
        def get_today_stats() -> dict:
            """Today's screen-habit counters (numbers only)."""
            s = coach.stats.snapshot()
            return {k: v for k, v in s.items() if k not in ("decider_p50_ms", "decider_p95_ms")}

        @tool
        def summarize_period(days: int = 7) -> dict:
            """Daily screen-habit counters for the last `days` days (numbers only)."""
            days = max(1, min(30, int(days)))
            rows = coach.stats.period(days)
            keep = ("day", "under30_min", "longest_bout_min", "breaks_offered", "breaks_verified", "squint_episodes",
                    "adaptations", "adaptations_worked", "glasses_off_min")
            return {"days": [{k: r.get(k) for k in keep} for r in rows]}

        @tool
        def write_doctrine(profile: dict, limits: dict, rules: list[dict]) -> dict:
            """Save a DRAFT rulebook (the user approves it in the dashboard). Rules may only reference the
            fact lines in the system prompt; each rule needs n, text, tool, args, when_true, when_false, basis."""
            coach._doctrine_attempts += 1
            if coach._doctrine_attempts > MAX_DOCTRINE_ATTEMPTS:
                return {"status": "error", "content": [{"text": "STOP: too many invalid attempts. Do not retry."}]}
            try:
                prof = Profile(**(profile or {}))
                lim = Limits(**{**Limits().model_dump(), **(limits or {})})
                parsed = [DoctrineRule(**{**r, "origin": "bedrock", "status": "active"}) for r in rules]
                if not parsed:
                    raise ValueError("rules must not be empty")
            except (ValidationError, ValueError, TypeError) as e:
                return {"status": "error", "content": [{"text": f"Invalid rulebook, fix and call write_doctrine again: {e}"}]}
            parsed = tidy_rules(parsed)
            d = coach.store.save_draft(coach._source_text, prof, lim, parsed)
            coach._doctrine_saved = d.version
            coach.bus.publish("doctrine", d.to_contract())
            return {"status": "success", "content": [{"text": f"Draft rulebook version {d.version} saved for approval."}]}

        @tool
        def propose_rule(rule_text: str, tool: str, when_true: str, when_false: str, reason: str,
                         moment_ids: list[str]) -> dict:
            """Propose ONE new rule for human approval, citing the moment ids that motivated it."""
            if tool not in TOOLS or tool == "reset":
                return {"status": "error", "content": [{"text": f"Unknown tool {tool!r}. Use one of {TOOLS[:-1]}."}]}
            try:
                rule = DoctrineRule(n=99, text=rule_text, tool=tool, when_true=when_true, when_false=when_false,
                                    basis=reason, origin="proposal", status="active")
            except ValidationError as e:
                return {"status": "error", "content": [{"text": f"Invalid rule: {e}"}]}
            pid = f"p_{next(coach._p_ids):06d}"
            ms = [{"t": m["t"], "note": m["note"]} for m in coach.moments.get(list(moment_ids or []))]
            data = {"id": pid, "rule_text": rule_text, "reason": reason, "moments": ms, "status": "pending"}
            coach.proposals[pid] = {"data": data, "rule": rule}
            coach.bus.publish("proposal", dict(data))
            return {"status": "success", "content": [{"text": f"Proposal {pid} sent for human approval."}]}

        @tool
        def draft_exam_request(subject: str, body: str) -> dict:
            """Save an eye-exam request email as a DRAFT. It is never sent automatically."""
            eid = f"e_{next(coach._e_ids):06d}"
            data = {"id": eid, "subject": subject[:200], "body": body[:4000], "status": "draft", "to": None}
            coach.drafts[eid] = data
            coach.bus.publish("email_draft", dict(data))  # a copy: the draft's status changes later
            return {"status": "success", "content": [{"text": f"Draft {eid} saved."}]}

        @tool
        def adopt_doctrine(version: int) -> dict:
            """Adopt (approve) a draft rulebook version. Requires the user's confirmation."""
            try:
                d = coach.store.approve(int(version))
            except StaleVersion as e:
                return {"status": "error", "content": [{"text": f"STALE: {e}"}]}
            coach.bus.publish("doctrine", d.to_contract())
            return {"status": "success", "content": [{"text": f"Rulebook version {d.version} is active."}]}

        @tool
        def open_exam_email(draft_id: str) -> dict:
            """Open the exam email draft in the user's mail app (mailto:). Requires confirmation. Never sends."""
            d = coach.drafts.get(draft_id)
            if d is None:
                return {"status": "error", "content": [{"text": f"No draft {draft_id}"}]}
            url = "mailto:" + urllib.parse.quote(d.get("to") or "") + "?" + urllib.parse.urlencode(
                {"subject": d["subject"], "body": d["body"]}, quote_via=urllib.parse.quote)
            if coach.startfile is not None:
                coach.startfile(url)
            d["status"] = "opened"
            coach.bus.publish("email_draft", dict(d))
            return {"status": "success", "content": [{"text": "Draft opened in the mail app. Nothing was sent."}]}

        return [get_today_stats, summarize_period, write_doctrine, propose_rule, draft_exam_request,
                adopt_doctrine, open_exam_email]

    # ---- flows (run on the 1-worker executor) ----------------------------------------------------
    def compile_doctrine(self, text: str) -> int | None:
        flags = red_flags(text)
        if flags:
            self.bus.toast("warning", "Some of what you describe (" + ", ".join(sorted(set(flags))) + ") can need "
                           "prompt care. Far Point is not a medical device: please contact an eye doctor soon.")
        if self._off():
            return None
        self._source_text = text.strip()[:2000]
        self._doctrine_attempts = 0
        self._doctrine_saved = None
        self._run_agent(DOCTRINE_TASK.format(text=self._source_text, defaults=default_rules_json()))
        if self._doctrine_saved is None:
            self.bus.toast("warning", "Could not build a valid rulebook from that description. The current rules stay.")
        return self._doctrine_saved

    def adopt(self, version: int) -> bool:
        """UI approve_doctrine: the click is the approval, so a single-use token passes the ConfirmGate."""
        self.broker.preapprove(f"doctrine:{int(version)}")
        res = self.direct.tool.adopt_doctrine(version=int(version))
        if res.get("status") != "success":
            txt = _text_of(res)
            if txt.startswith("STALE:"):
                self.bus.toast("warning", f"That rulebook version ({version}) is out of date; showing the current one.")
                self.bus.publish("doctrine", self.store.current_draft.to_contract())
            else:
                self.bus.toast("warning", f"Rulebook not adopted: {txt[:160]}")
            return False
        return True

    def report(self, period: str = "today") -> dict | None:
        if self._off():
            return None
        result = self._run_agent(REPORT_TASK.format(period="today" if period == "today" else "the last 7 days"))
        body = strip_html(str(result).strip()) or "No data yet."
        data = {"id": f"r_{next(self._r_ids):06d}", "period": period, "markdown": f"{DISCLAIMER}\n\n{body}",
                "model": self.model_id, "generated_at": int(self.clock() * 1000)}
        self.bus.publish("report", data)
        return data

    def review_moments(self, force: bool = False) -> int:
        items = self.moments.unreviewed()
        if not items or (len(items) < REVIEW_MIN_MOMENTS and not force):
            return 0
        if not self.enabled:
            return 0
        lines = "\n".join(f"- {m['id']} {m['kind']}: {m['note']} {json.dumps(m.get('data', {}))}" for m in items[-40:])
        before = len(self.proposals)
        self._run_agent(REVIEW_TASK.format(moments=lines))
        self.moments.mark_reviewed([m["id"] for m in items])
        self._last_review = self.clock()
        return len(self.proposals) - before

    def approve_proposal(self, pid: str) -> bool:
        p = self.proposals.get(pid)
        if p is None or p["data"]["status"] != "pending":
            self.bus.toast("warning", f"No pending proposal {pid}.")
            return False
        d = self.store.add_rule(p["rule"])
        p["data"] = {**p["data"], "status": "approved"}
        self.bus.publish("proposal", p["data"])
        self.bus.publish("doctrine", d.to_contract())
        return True

    def reject_proposal(self, pid: str) -> bool:
        p = self.proposals.get(pid)
        if p is None or p["data"]["status"] != "pending":
            self.bus.toast("warning", f"No pending proposal {pid}.")
            return False
        p["data"] = {**p["data"], "status": "rejected"}
        self.bus.publish("proposal", p["data"])
        return True

    def draft_exam(self) -> str | None:
        if self._off():
            return None
        before = set(self.drafts)
        self._run_agent(EMAIL_TASK)
        new = [e for e in self.drafts if e not in before]
        if not new:
            self.bus.toast("warning", "Could not draft the email this time.")
            return None
        eid = new[-1]
        self.drafts[eid]["status"] = "pending_confirm"

        def on_answer(approve: bool) -> None:
            if approve:
                self.broker.preapprove(f"email:{eid}")
                self.submit(lambda: self.direct.tool.open_exam_email(draft_id=eid))
            else:
                self.drafts[eid]["status"] = "draft"
                self.bus.publish("email_draft", dict(self.drafts[eid]))

        self.broker.request_async("Open email draft in your mail app?",
                                  "Far Point will open a mailto: link. Nothing is sent until you press Send yourself.",
                                  on_answer)
        self.bus.publish("email_draft", dict(self.drafts[eid]))
        return eid

    # ---- periodic ------------------------------------------------------------------------------
    def trend_up(self) -> bool:
        days = self.stats.period(7)
        for key in ("under30_min", "squint_episodes"):
            vals = [d.get(key, 0) for d in days]
            run = 0
            for a, b in zip(vals, vals[1:]):
                run = run + 1 if b > a else 0
                if run >= 3:
                    return True
        return False

    def on_time(self, t: float) -> None:
        """Called from the pulse thread; schedules work on the coach executor."""
        if not self.enabled:
            return
        if t - self._last_review >= REVIEW_EVERY_S and len(self.moments.unreviewed()) >= REVIEW_MIN_MOMENTS:
            self._last_review = t
            self.submit(self.review_moments)
        if (self._last_trend_email is None or t - self._last_trend_email >= 7 * 86400) and int(t) % 3600 < 2:
            if self.trend_up():
                self._last_trend_email = t
                self.submit(self.draft_exam)

    def close(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)
