"""Smoke test of vision mode against the real local Decider (plumbing, not accuracy).

  python scripts/smoke_vision.py                 # restart in vision mode, test, restart text mode
  python scripts/smoke_vision.py --keep-vision   # leave the vision server running (after an S2 pass)

1. Restarts the Decider with -Vision (if needed) and sends one warm-up image (a gray
   synthetic frame, not the camera).
2. Runs the real live loop for --seconds with vision forced on, dry-run actuators and Bedrock
   off: the real camera, one webcam frame per tick to the LOCAL server, in memory only.
3. Reports decisions with `answers.vision`, vision and text latency, schema errors, GPU memory.
4. Restarts the Decider in text mode unless --keep-vision.
Accuracy is S2's job (eval/spike_s2.py); this only proves the path works end to end.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import decider_ctl  # noqa: E402

from farpoint.config import Settings  # noqa: E402
from farpoint.contract import errors  # noqa: E402
from farpoint.runtime import Runtime  # noqa: E402

RUNTIME = Path(os.environ.get("FARPOINT_RUNTIME", r"E:\farpoint-runtime"))


def run(seconds: float, keep_vision: bool, out: Path | None = None) -> dict:
    report: dict = {"gpu_before_mib": decider_ctl.gpu_used_mib()}
    report["restart_vision"] = decider_ctl.restart(vision=True)
    ok = report["restart_vision"]["ok"]
    if ok:
        report["warm_up"] = decider_ctl.warm_up_vision()
        ok &= report["warm_up"]["ok"]
    if ok:
        scratch = RUNTIME / "smoke-vision"
        shutil.rmtree(scratch, ignore_errors=True)
        rt = Runtime(Settings(mode="live", runtime_dir=scratch, no_bedrock=True, dry_run=True, vision=True))
        events: list[dict] = []
        rt.bus.add_listener(events.append)
        rt.start()
        try:
            time.sleep(seconds)
            report["gpu_during_mib"] = decider_ctl.gpu_used_mib()
        finally:
            rt.stop()
        decs = [e["data"] for e in events if e["type"] == "decision"]
        vis = [d for d in decs if "vision" in d["answers"]]
        vlat = [d["vision_latency_ms"] for d in vis]
        tlat = [d["latency_ms"] for d in decs if d["source"] == "decider"]
        hello = next((e["data"] for e in reversed(events) if e["type"] == "hello"), {})
        report["loop"] = {
            "seconds": seconds, "camera_frames": getattr(rt.source, "frames", None),
            "frames_with_face": getattr(rt.source, "faces", None),
            "decisions": len(decs), "with_vision_answers": len(vis),
            "fallback": sum(d["source"] == "fallback" for d in decs),
            "vision_latency_ms_p50": round(statistics.median(vlat), 1) if vlat else None,
            "text_latency_ms_p50": round(statistics.median(tlat), 1) if tlat else None,
            "last_vision_answers": vis[-1]["answers"]["vision"] if vis else None,
            "glasses_line": next((ln for ln in (decs[-1]["state_text"].splitlines() if decs else [])
                                  if ln.startswith("- Glasses:")), None),
            "hello_decider_vision": hello.get("decider", {}).get("vision"),
            "schema_errors": [e["type"] for e in events if errors(e, "ServerEvent")],
            "note": "webcam frames went to 127.0.0.1 only, in memory; none written to disk",
        }
        lp = report["loop"]
        ok &= lp["with_vision_answers"] > 0 and not lp["schema_errors"] and lp["hello_decider_vision"] is True
    if not keep_vision:
        report["restart_text"] = decider_ctl.restart(vision=False)
        ok &= report["restart_text"]["ok"]
    report["gpu_after_mib"] = decider_ctl.gpu_used_mib()
    report["ok"] = bool(ok)
    if out:
        out.write_text(json.dumps(report, indent=2))
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=20.0)
    ap.add_argument("--keep-vision", action="store_true")
    ap.add_argument("--out", type=Path)
    a = ap.parse_args(argv)
    report = run(a.seconds, a.keep_vision, a.out)
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
