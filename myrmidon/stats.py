"""Today's counters (contract `stats`), saved daily under <profile>/daily/YYYY-MM-DD.json."""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

from . import privacy

FIELDS = (
    "under30_min", "longest_bout_min", "breaks_offered", "breaks_verified", "streak",
    "squint_episodes", "glasses_off_min", "adaptations", "adaptations_worked", "decisions",
    "decider_p50_ms", "decider_p95_ms", "face_images_uploaded", "bedrock_calls", "bedrock_tokens",
)
SAVE_EVERY_S = 60.0
LATENCY_WINDOW = 500
# Amazon Nova Lite on-demand list price (us-east-1), used only for the spend estimate in the usage log.
NOVA_LITE_USD_PER_1K_IN = 0.00006
NOVA_LITE_USD_PER_1K_OUT = 0.00024


def _pct(xs: list[float], q: float) -> float:
    if not xs:
        return 0.0
    xs = sorted(xs)
    k = (len(xs) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


class StatsStore:
    def __init__(self, profile_dir: Path, clock=time.time):
        self.dir = Path(profile_dir) / "daily"
        self.clock = clock
        self._lock = threading.RLock()
        self._day = self._today()
        self._c: dict[str, float] = {k: 0 for k in FIELDS}
        self._lat: list[float] = []
        self._last_save = clock()
        self._load(self._day)

    def _today(self) -> str:
        return datetime.fromtimestamp(self.clock()).strftime("%Y-%m-%d")

    def _path(self, day: str) -> Path:
        return self.dir / f"{day}.json"

    def _load(self, day: str) -> None:
        p = self._path(day)
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            for k in FIELDS:
                if k in data and k != "face_images_uploaded":
                    self._c[k] = data[k]
            self._lat = list(data.get("_latencies", []))[-LATENCY_WINDOW:]

    def _rollover(self) -> None:
        day = self._today()
        if day != self._day:
            self.save()
            self._day = day
            self._c = {k: 0 for k in FIELDS}
            self._lat = []

    def inc(self, key: str, n: float = 1) -> None:
        with self._lock:
            self._rollover()
            self._c[key] = self._c.get(key, 0) + n

    def set(self, key: str, value: float) -> None:
        with self._lock:
            self._rollover()
            self._c[key] = value

    def set_max(self, key: str, value: float) -> None:
        with self._lock:
            self._rollover()
            self._c[key] = max(self._c.get(key, 0), value)

    def get(self, key: str) -> float:
        with self._lock:
            return self._c.get(key, 0)

    def record_decider_latency(self, ms: float) -> None:
        with self._lock:
            self._rollover()
            self._lat.append(float(ms))
            del self._lat[:-LATENCY_WINDOW]
            self._c["decisions"] += 1

    def record_bedrock(self, calls: int, tokens: int, who: str = "", model: str = "",
                       input_tokens: int | None = None, output_tokens: int | None = None) -> None:
        """Count Bedrock usage and append it to <profile>/bedrock-usage.jsonl (tokens only)."""
        with self._lock:
            self._rollover()
            self._c["bedrock_calls"] += calls
            self._c["bedrock_tokens"] += tokens
            inp = input_tokens if input_tokens is not None else tokens
            out = output_tokens if output_tokens is not None else 0
            row = {"t": round(self.clock(), 1), "who": who, "model": model, "calls": calls,
                   "input_tokens": inp, "output_tokens": out,
                   "est_usd": round(inp / 1000 * NOVA_LITE_USD_PER_1K_IN + out / 1000 * NOVA_LITE_USD_PER_1K_OUT, 6)}
            self.dir.parent.mkdir(parents=True, exist_ok=True)
            with (self.dir.parent / "bedrock-usage.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps(row) + "\n")

    def update_from_tracker(self, view: dict) -> None:
        """Per-day perception counters owned by the SignalTracker."""
        with self._lock:
            self._rollover()
            for k in ("under30_min", "squint_episodes", "glasses_off_min"):
                self._c[k] = view[k]
            self._c["longest_bout_min"] = max(self._c["longest_bout_min"], view["longest_bout_min"])

    def _data(self) -> dict:
        out = {"day": self._day}
        for k in FIELDS:
            v = self._c.get(k, 0)
            out[k] = round(float(v), 2) if isinstance(v, float) and not float(v).is_integer() else int(v)
        out["decider_p50_ms"] = round(_pct(self._lat, 0.5), 1)
        out["decider_p95_ms"] = round(_pct(self._lat, 0.95), 1)
        out["face_images_uploaded"] = privacy.FACE_IMAGES_UPLOADED
        return out

    def snapshot(self) -> dict:
        with self._lock:
            self._rollover()
            return self._data()

    def on_time(self, t: float) -> None:
        if t - self._last_save >= SAVE_EVERY_S:
            self.save()

    def save(self) -> None:
        with self._lock:
            self.dir.mkdir(parents=True, exist_ok=True)
            data = self._data()
            data["_latencies"] = self._lat[-LATENCY_WINDOW:]
            tmp = self._path(self._day).with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
            tmp.replace(self._path(self._day))
            self._last_save = self.clock()

    def period(self, days: int) -> list[dict]:
        """The last `days` days (today included), oldest first. Numbers only."""
        with self._lock:
            self.save()
            today = datetime.fromtimestamp(self.clock()).date()
            out = []
            for i in range(days - 1, -1, -1):
                day = (today - timedelta(days=i)).strftime("%Y-%m-%d")
                p = self._path(day)
                if p.exists():
                    data = json.loads(p.read_text(encoding="utf-8"))
                    data.pop("_latencies", None)
                    out.append(data)
            return out
