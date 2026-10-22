"""What Far Point learns about this user: which adaptations work where, and the moments
worth a human look (unsure, escalated, demoted, asked). Numbers and short notes only."""
from __future__ import annotations

import itertools
import json
import threading
import time
from pathlib import Path

DEMOTE_MIN_TRIALS = 3
DEMOTE_WORKED_RATE = 0.25


class PreferenceStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.Lock()
        self.data = {"outcomes": {}, "asks": []}
        if self.path.exists():
            self.data.update(json.loads(self.path.read_text(encoding="utf-8")))

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=1), encoding="utf-8")
        tmp.replace(self.path)

    @staticmethod
    def _key(tool: str, category: str) -> str:
        return f"{tool}|{category}"

    def record(self, tool: str, category: str, outcome: str) -> None:
        with self._lock:
            c = self.data["outcomes"].setdefault(self._key(tool, category),
                                                 {"worked": 0, "no_change": 0, "worse": 0, "n/a": 0})
            c[outcome] = c.get(outcome, 0) + 1
            self._save()

    def record_ask(self, question: str, approve: bool, t: float | None = None) -> None:
        with self._lock:
            self.data["asks"].append({"t": t or time.time(), "question": question, "approve": bool(approve)})
            self._save()

    def counts(self, tool: str, category: str) -> dict:
        with self._lock:
            return dict(self.data["outcomes"].get(self._key(tool, category), {}))

    def demoted(self, tool: str, category: str) -> bool:
        c = self.counts(tool, category)
        trials = c.get("worked", 0) + c.get("no_change", 0) + c.get("worse", 0)
        return trials >= DEMOTE_MIN_TRIALS and c.get("worked", 0) / trials < DEMOTE_WORKED_RATE


class MomentLog:
    """JSONL log of moments: `unsure`, `escalated`, `demoted`, `ask`, `denied`."""

    def __init__(self, path: Path, clock=time.time):
        self.path = Path(path)
        self.clock = clock
        self._lock = threading.Lock()
        self._items: list[dict] = []
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    self._items.append(json.loads(line))
        start = max((int(m["id"].split("_")[1]) for m in self._items), default=0) + 1
        self._ids = itertools.count(start)

    def log(self, kind: str, note: str, **numbers) -> dict:
        m = {"id": f"m_{next(self._ids):06d}", "t": int(self.clock() * 1000), "kind": kind, "note": note[:300],
             "data": numbers, "reviewed": False}
        with self._lock:
            self._items.append(m)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(m) + "\n")
        return m

    def unreviewed(self, kinds: set[str] | None = None) -> list[dict]:
        with self._lock:
            return [m for m in self._items if not m["reviewed"] and (kinds is None or m["kind"] in kinds)]

    def get(self, ids: list[str]) -> list[dict]:
        want = set(ids)
        with self._lock:
            return [m for m in self._items if m["id"] in want]

    def recent(self, n: int = 50) -> list[dict]:
        with self._lock:
            return list(self._items[-n:])

    def mark_reviewed(self, ids: list[str]) -> None:
        want = set(ids)
        with self._lock:
            for m in self._items:
                if m["id"] in want:
                    m["reviewed"] = True
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text("".join(json.dumps(m) + "\n" for m in self._items), encoding="utf-8")
            tmp.replace(self.path)
