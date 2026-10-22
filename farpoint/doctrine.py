"""The user's rulebook ("doctrine"): numbered, priority-ordered rules, one tool each.

Rules carry explicit `when_true` / `when_false` criteria that quote the lines
`farpoint.facts.render_state` writes. Numeric knobs live in `Limits` and are clamped to
safe ranges in code, whoever wrote them (default, Bedrock, the user).
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from patterns.reflex_gate import Rule

TOOLS = (
    "enlarge_text", "reduce_text", "dim_screen", "brighten_screen", "dark_mode",
    "far_look_break", "glasses_reminder", "ask_user", "reset",
)
ToolName = Literal[
    "enlarge_text", "reduce_text", "dim_screen", "brighten_screen", "dark_mode",
    "far_look_break", "glasses_reminder", "ask_user", "reset",
]

CLOUCLIP_SOURCE = (
    "Cao Y, Lan W, Wen L, et al. An effectiveness study of a wearable device (Clouclip) intervention "
    "in unhealthy visual behaviors among school-age children: A pilot study. Medicine (Baltimore) "
    "2020;99(2):e17992. PMID 31914011. https://pubmed.ncbi.nlm.nih.gov/31914011/ "
    "(cohort: school-age children)"
)

# Safe range for every knob. Values outside are clamped, never rejected.
LIMIT_RANGES: dict[str, tuple[float, float]] = {
    "near_cm": (20, 40),
    "near_s": (3, 60),
    "bout_cm": (40, 80),
    "bout_min": (10, 90),
    "bout_reset_s": (5, 300),
    "relaxed_cm": (35, 80),
    "relaxed_min": (5, 60),
    "squint_ratio": (0.5, 0.95),
    "squint_s": (1, 30),
    "lean_in_cm": (3, 20),
    "low_blink_per_min": (4, 20),
    "dim_pct_high": (40, 100),
    "bright_pct_low": (0, 60),
}


class Limits(BaseModel):
    near_cm: float = 30
    near_s: float = 5
    bout_cm: float = 60
    bout_min: float = 45
    bout_reset_s: float = 20
    relaxed_cm: float = 50
    relaxed_min: float = 10
    squint_ratio: float = 0.75
    squint_s: float = 3
    lean_in_cm: float = 8
    low_blink_per_min: float = 10
    dim_pct_high: float = 70
    bright_pct_low: float = 30

    @field_validator("*", mode="before")
    @classmethod
    def _clamp(cls, v, info):
        lo, hi = LIMIT_RANGES[info.field_name]
        return min(hi, max(lo, float(v)))


class DoctrineRule(BaseModel):
    n: int = Field(ge=1)
    text: str = Field(min_length=3, max_length=400)
    tool: ToolName
    args: dict = Field(default_factory=dict)
    when_true: str = Field(min_length=3, max_length=400)
    when_false: str = Field(min_length=3, max_length=400)
    basis: str = ""
    origin: Literal["bedrock", "user", "proposal", "default"] = "default"
    status: Literal["active", "pending", "rejected"] = "active"


class Profile(BaseModel):
    glasses_for_screen: Literal["yes", "no", "unknown"] = "unknown"
    conditions: list[str] = Field(default_factory=list)


class Doctrine(BaseModel):
    version: int = Field(ge=0)
    source_text: str = ""
    approved: bool = False
    profile: Profile = Field(default_factory=Profile)
    limits: Limits = Field(default_factory=Limits)
    rules: list[DoctrineRule]

    def to_contract(self) -> dict:
        return {
            "version": self.version,
            "source_text": self.source_text,
            "approved": self.approved,
            "rules": [
                {"n": r.n, "text": r.text, "origin": r.origin, "status": r.status, "basis": r.basis}
                for r in sorted(self.rules, key=lambda r: r.n)
            ],
        }

    def active_rules(self) -> list[DoctrineRule]:
        return sorted((r for r in self.rules if r.status == "active"), key=lambda r: r.n)

    def to_pattern_rules(self) -> list[Rule]:
        return [Rule(r.n, r.tool, r.text, r.when_true, r.when_false) for r in self.active_rules()]

    def rule(self, n: int) -> DoctrineRule | None:
        return next((r for r in self.rules if r.n == n), None)


DEFAULT_ARGS = {
    "enlarge_text": {"steps": 1},
    "reduce_text": {"steps": 1},
    "dim_screen": {"level": 0.5},
    "brighten_screen": {"level": 0.8},
    "dark_mode": {"on": True},
    "far_look_break": {"target_s": 20},
    "glasses_reminder": {},
    "ask_user": {"question": "You have squinted for over a minute even with text enlarged twice. "
                             "Take a 20-second far-look break now?"},
    "reset": {},
}

_DEFAULT_RULES = [
    dict(
        n=1, tool="enlarge_text",
        text="The Viewing distance line says enlarging needed.",
        when_true="the Viewing distance line says 'enlarging needed'",
        when_false="the Viewing distance line says 'no enlarging needed', 'no enlarging needed yet', 'no face visible' or 'this app has no zoom control'",
        basis="Clouclip pilot: under 30 cm for more than 5 s counts as unhealthy near work. Larger text lets you lean back.",
    ),
    dict(
        n=2, tool="glasses_reminder",
        text="The Glasses line says reminder due.",
        when_true="the Glasses line ends with 'reminder due'",
        when_false="the Glasses line ends with 'no reminder needed'",
        basis="Leaning in and squinting at once is a common sign of reading without your prescribed glasses.",
    ),
    dict(
        n=3, tool="dark_mode",
        text="The Theme line says dark mode needed.",
        when_true="the Theme line says 'mismatch, dark mode needed'",
        when_false="the Theme line says 'no change needed'",
        basis="A bright light page in a dark room is a common glare complaint.",
    ),
    dict(
        n=4, tool="dim_screen",
        text="The Screen brightness line says dimming needed.",
        when_true="the Screen brightness line says 'dimming needed'",
        when_false="the Screen brightness line says 'no change needed', 'brightening needed' or 'not adjustable'",
        basis="A screen much brighter than a dark room adds glare. Rule 3 (dark mode) comes first.",
    ),
    dict(
        n=5, tool="brighten_screen",
        text="The Screen brightness line says brightening needed.",
        when_true="the Screen brightness line says 'brightening needed'",
        when_false="the Screen brightness line says 'no change needed', 'dimming needed' or 'not adjustable'",
        basis="A dim screen in a bright room makes you lean in and squint.",
    ),
    dict(
        n=6, tool="far_look_break",
        text="The Near-work bout line says break is due.",
        when_true="the Near-work bout line ends with 'break is due'",
        when_false="the Near-work bout line ends with 'break not due yet'",
        basis="Clouclip pilot: under 60 cm for more than 45 min counts as unhealthy near work. A 20 s far look breaks the bout.",
    ),
    dict(
        n=7, tool="reduce_text",
        text="The Relaxed reading line says text can go back one step.",
        when_true="the Relaxed reading line ends with 'text can go back one step'",
        when_false="the Relaxed reading line ends with 'no change needed'",
        basis="Undo Far Point's own zoom once you have read comfortably for a while.",
    ),
    dict(
        n=8, tool="ask_user",
        text="The Squint despite zoom line says yes.",
        when_true="the Squint despite zoom line ends with 'yes'",
        when_false="the Squint despite zoom line ends with 'no'",
        basis="If enlarging text has not helped, ask you instead of guessing. At most once per 30 min.",
    ),
]


def default_doctrine() -> Doctrine:
    rules = [DoctrineRule(**r, args=DEFAULT_ARGS[r["tool"]], origin="default", status="active")
             for r in _DEFAULT_RULES]
    return Doctrine(version=1, source_text="", approved=True, profile=Profile(), limits=Limits(), rules=rules)


class StaleVersion(Exception):
    """approve() was called with a version that is not the current draft."""


class DoctrineStore:
    """Versioned doctrine, persisted as JSON under `<profile_dir>/doctrine.json`."""

    def __init__(self, profile_dir: Path):
        self.path = Path(profile_dir) / "doctrine.json"
        self._lock = threading.RLock()
        self._active: Doctrine
        self._draft: Doctrine | None = None
        if self.path.exists():
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self._active = Doctrine(**data["active"])
            self._draft = Doctrine(**data["draft"]) if data.get("draft") else None
            self._max_version = int(data.get("max_version", self._active.version))
        else:
            self._active = default_doctrine()
            self._max_version = self._active.version
            self._save()

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "active": self._active.model_dump(),
            "draft": self._draft.model_dump() if self._draft else None,
            "max_version": self._max_version,
        }
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    @property
    def active(self) -> Doctrine:
        with self._lock:
            return self._active

    @property
    def current_draft(self) -> Doctrine:
        """What the UI shows: a pending draft newer than the active doctrine, else the active one."""
        with self._lock:
            if self._draft is not None and self._draft.version > self._active.version:
                return self._draft
            return self._active

    def save_draft(self, source_text: str, profile: Profile, limits: Limits, rules: list[DoctrineRule]) -> Doctrine:
        with self._lock:
            self._max_version += 1
            ordered = sorted(rules, key=lambda r: r.n)
            renumbered = [r.model_copy(update={"n": i}) for i, r in enumerate(ordered, 1)]
            self._draft = Doctrine(version=self._max_version, source_text=source_text, approved=False,
                                   profile=profile, limits=limits, rules=renumbered)
            self._save()
            return self._draft

    def approve(self, version: int) -> Doctrine:
        with self._lock:
            pending = self._draft is not None and self._draft.version > self._active.version
            if pending and self._draft.version == version:
                self._active = self._draft.model_copy(update={"approved": True})
                self._draft = None
                self._save()
                return self._active
            if version == self._active.version and not pending:
                return self._active  # already active, nothing newer waiting: idempotent
            raise StaleVersion(f"version {version} is not the current draft "
                               f"(draft={self._draft.version if self._draft else None}, active={self._active.version})")

    def add_rule(self, rule: DoctrineRule) -> Doctrine:
        """Add a human-approved rule to the active doctrine. It goes above any ask_user rule."""
        with self._lock:
            rules = list(self._active.active_rules()) + [r for r in self._active.rules if r.status != "active"]
            ask = [r for r in rules if r.tool == "ask_user"]
            rest = [r for r in rules if r.tool != "ask_user"]
            ordered = sorted(rest, key=lambda r: r.n) + [rule] + sorted(ask, key=lambda r: r.n)
            renumbered = [r.model_copy(update={"n": i}) for i, r in enumerate(ordered, 1)]
            self._max_version += 1
            self._active = self._active.model_copy(update={"version": self._max_version, "rules": renumbered,
                                                           "approved": True})
            self._save()
            return self._active
