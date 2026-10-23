"""Spike S2: Decider image mode over webcam frames.

Frames never enter the repository. Live frames stay in memory; a guided labeled
capture writes to MYRMIDON_RUNTIME (E:\\myrmidon-runtime by default), outside the repo.
The questions and state are imported from myrmidon/vision.py, the same request the
optional vision mode sends (the wording measured in Phase 1, unchanged).

Usage:
  python eval/spike_s2.py latency --n 40          # VRAM peak + latency on live frames (no labels)
  python eval/spike_s2.py capture --glasses-source own|prop --glasses-for-screen yes|no|unknown
                                                   # guided labeled capture (a person poses on prompts)
  python eval/spike_s2.py score                    # accuracy on the captured labeled frames
  python eval/spike_s2.py decide                   # writes results/s2_decision.json + SPIKE_RESULTS.md
Writes results/s2_<mode>.json.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import statistics
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from myrmidon import decide  # noqa: E402
from myrmidon.vision import GATED, S2_QUESTIONS, S2_STATE  # noqa: E402

RUNTIME = Path(os.environ.get("MYRMIDON_RUNTIME", r"E:\myrmidon-runtime"))
FRAMES_DIR = RUNTIME / "s2-frames"
RESULTS = ROOT / "results"
WARMUP = 3
P50_LIMIT_S = 1.5
VRAM_LIMIT_MIB = int(7.4 * 1024)
ACC_LIMIT = 0.85

STATE = S2_STATE
QUESTIONS = S2_QUESTIONS

# Guided capture plan: (prompt, labels). 8 frames per pose, 6 poses = 48 frames.
POSES = [
    ("Glasses ON, look at the screen", {"glasses_on": True, "looking_far_away": False, "rubbing_eyes": False}),
    ("Glasses ON, look far away (across the room / out of a window)", {"glasses_on": True, "looking_far_away": True, "rubbing_eyes": False}),
    ("Glasses OFF, look at the screen", {"glasses_on": False, "looking_far_away": False, "rubbing_eyes": False}),
    ("Glasses OFF, look far away (across the room / out of a window)", {"glasses_on": False, "looking_far_away": True, "rubbing_eyes": False}),
    ("Glasses OFF, rub your eyes", {"glasses_on": False, "looking_far_away": False, "rubbing_eyes": True}),
    ("Glasses ON, look at the screen, lean in close", {"glasses_on": True, "looking_far_away": False, "rubbing_eyes": False}),
]
FRAMES_PER_POSE = 8
PREP_S = 5

SPIKE_RESULTS = ROOT / "eval" / "SPIKE_RESULTS.md"
MARK_START, MARK_END = "<!-- s2-rerun:start -->", "<!-- s2-rerun:end -->"


def beep(times: int = 1) -> None:
    try:
        import winsound
        for _ in range(times):
            winsound.Beep(1000, 150)
            time.sleep(0.08)
    except (ImportError, RuntimeError):
        print("\a", end="", flush=True)


class VramMonitor(threading.Thread):
    def __init__(self, period=0.2):
        super().__init__(daemon=True)
        self.period, self.samples, self._halt = period, [], threading.Event()

    def run(self):
        while not self._halt.is_set():
            self.samples.append(gpu_used_mib())
            time.sleep(self.period)

    def stop(self):
        self._halt.set()
        self.join()
        return max(self.samples) if self.samples else None


def gpu_used_mib() -> int:
    out = subprocess.check_output(
        ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"], text=True
    )
    return int(out.strip().splitlines()[0])


def encode(frame) -> str:
    import cv2
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
    if not ok:
        raise RuntimeError("jpeg encode failed")
    return base64.b64encode(buf.tobytes()).decode("ascii")


def ask_frame(b64: str) -> tuple[dict, float]:
    t0 = time.perf_counter()
    resp = decide.client().ask(STATE, QUESTIONS, images=[b64], timeout=600.0)  # same process-wide lock
    return resp, time.perf_counter() - t0


def pct(xs, q):
    xs = sorted(xs)
    k = (len(xs) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def cmd_latency(a):
    from myrmidon.sense import open_camera
    cap = open_camera(a.camera)
    try:
        for _ in range(10):
            cap.read()
        frames = []
        while len(frames) < a.n + WARMUP:
            ok, f = cap.read()
            if ok:
                frames.append(encode(f))
            time.sleep(0.05)
    finally:
        cap.release()
    mon = VramMonitor()
    mon.start()
    lat, answers = [], []
    try:
        for i, b in enumerate(frames):
            resp, dt = ask_frame(b)
            if i >= WARMUP:
                lat.append(dt)
                answers.append({k: v["noul"] for k, v in resp["answers"].items()})
    finally:
        peak = mon.stop()
    summary = {
        "n": len(lat),
        "client_s": {"p50": statistics.median(lat), "p90": pct(lat, 0.9), "max": max(lat)},
        "peak_gpu_used_mib": peak,
        "vram_limit_mib": VRAM_LIMIT_MIB,
        "baseline_no_decider_mib": a.baseline_mib,
        "vision_server_footprint_mib": (peak - a.baseline_mib) if a.baseline_mib else None,
        "pass_latency": statistics.median(lat) <= P50_LIMIT_S,
        "pass_vram": peak is not None and peak <= VRAM_LIMIT_MIB,
        "unlabeled_answer_means": {k: statistics.mean(x[k] for x in answers) for k in QUESTIONS},
        "note": "live frames held in memory only; none written to disk",
    }
    out = RESULTS / "s2_latency.json"
    out.write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


def _wait(cap, seconds: float) -> None:
    end = time.time() + seconds
    while time.time() < end:
        cap.read()  # keep the camera buffer fresh


def cmd_capture(a):
    import cv2
    from myrmidon.sense import open_camera
    FRAMES_DIR.mkdir(parents=True, exist_ok=True)
    for old in FRAMES_DIR.glob("pose*_*.jpg"):  # a re-run replaces the previous capture
        old.unlink()
    cap = open_camera(a.camera)
    pv = None
    if a.preview:  # camera preview with the prompt and countdown drawn on top (display only)
        from myrmidon.preview import Preview
        pv = Preview("Myrmidon setup - labeled capture")

    def wait_show(seconds: float, lines, big=None) -> None:
        end = time.time() + seconds
        while time.time() < end:
            ok, f = cap.read()  # also keeps the camera buffer fresh
            if pv is not None and ok:
                pv.show(f, lines, big)

    labels, per_pose = [], []
    t_start = time.time()
    try:
        wait_show(1.0, ["Labeled capture: 6 poses, about 1 minute"])
        prev_glasses = None
        for pi, (prompt, lab) in enumerate(POSES):
            prep = PREP_S + (2 if prev_glasses is not None and prev_glasses != lab["glasses_on"] else 0)
            prev_glasses = lab["glasses_on"]
            print(f"\n==== Pose {pi + 1} of {len(POSES)} ====")
            print(f"   {prompt.upper()}")
            print("   Get into position. Capture starts at the beep and ends at the double beep.")
            head = [f"POSE {pi + 1} OF {len(POSES)}: {prompt.upper()}",
                    "Get into position. Capture starts at the beep, ends at the double beep."]
            for s in range(prep, 0, -1):
                print(f"\r   starting in {s} s ", end="", flush=True)
                wait_show(1.0, head, str(s))
            beep(1)
            print("\r   capturing, hold the pose...   ", end="", flush=True)
            lumas, n = [], 0
            for k in range(FRAMES_PER_POSE):
                ok, f = cap.read()
                if not ok:
                    continue
                name = f"pose{pi}_{k}.jpg"
                cv2.imwrite(str(FRAMES_DIR / name), f)  # the original frame; the preview is a mirrored copy
                lumas.append(float(cv2.cvtColor(f, cv2.COLOR_BGR2GRAY).mean()))
                labels.append({"file": name, **lab})
                n += 1
                wait_show(0.4, [head[0], f"CAPTURING {n}/{FRAMES_PER_POSE}: hold the pose"], "HOLD")
            beep(2)
            print("\r   done                          ")
            per_pose.append({"pose": pi, "prompt": prompt, "labels": lab, "frames": n,
                             "mean_luma": round(statistics.mean(lumas), 1) if lumas else None})
        wait_show(1.0, ["Capture done. Thank you."], "DONE")
    finally:
        cap.release()
        if pv is not None:
            pv.close()
    (FRAMES_DIR / "labels.json").write_text(json.dumps(labels, indent=2))
    dark = [p["pose"] for p in per_pose if p["mean_luma"] is not None and p["mean_luma"] < 40]
    summary = {
        "date": datetime.now().isoformat(timespec="seconds"),
        "n_frames": len(labels),
        "frames_per_pose": FRAMES_PER_POSE,
        "per_pose": per_pose,
        "glasses_source": a.glasses_source,
        "glasses_source_note": {"own": "the user's own glasses",
                                "prop": "a borrowed or spare pair used as a prop (the user has no glasses of their own)"
                                }[a.glasses_source],
        "glasses_for_screen": a.glasses_for_screen,
        "dark_poses": dark,
        "seconds": round(time.time() - t_start, 1),
        "frames_location": "outside the repository (MYRMIDON_RUNTIME/s2-frames); never committed",
    }
    (RESULTS / "s2_capture.json").write_text(json.dumps(summary, indent=2))
    if dark:
        print(f"warning: poses {dark} were very dark (mean brightness < 40/255); light your face and re-run")
    print(f"wrote {len(labels)} labeled frames to {FRAMES_DIR} and results/s2_capture.json")


def cmd_score(a):
    labels_path = FRAMES_DIR / "labels.json"
    if not labels_path.exists():
        print(f"no labeled capture at {labels_path}: run `python eval/spike_s2.py capture` first")
        return 2
    labels = json.loads(labels_path.read_text())
    info = decide.client().health_info()
    if not (info and info.get("vision")):
        print("the Decider server is not in vision mode: run .\\scripts\\start_decider.ps1 -Vision first")
        return 3
    for lab in labels[:WARMUP]:
        ask_frame(base64.b64encode((FRAMES_DIR / lab["file"]).read_bytes()).decode("ascii"))
    rows, lat = [], []
    for lab in labels:
        b = base64.b64encode((FRAMES_DIR / lab["file"]).read_bytes()).decode("ascii")
        resp, dt = ask_frame(b)
        lat.append(dt)
        rows.append({"file": lab["file"], "label": {k: lab[k] for k in QUESTIONS},
                     "p": {k: v["noul"] for k, v in resp["answers"].items()}})
    acc = {k: sum((r["p"][k] > 0.5) == r["label"][k] for r in rows) / len(rows) for k in QUESTIONS}
    summary = {
        "n": len(rows),
        "accuracy": acc,
        "client_s": {"p50": statistics.median(lat), "p90": pct(lat, 0.9)},
        "pass_accuracy": all(acc[k] >= ACC_LIMIT for k in GATED),
    }
    (RESULTS / "s2_score.json").write_text(json.dumps({"summary": summary, "rows": rows}, indent=2))
    print(json.dumps(summary, indent=2))
    return 0


def decide_s2(score_path: Path, capture_path: Path, out_path: Path, spike_results: Path | None,
              now: datetime | None = None) -> dict:
    """Apply the preregistered S2 rule to a score file and record the mode decision."""
    score = json.loads(Path(score_path).read_text())["summary"]
    cap = json.loads(Path(capture_path).read_text()) if Path(capture_path).exists() else {}
    acc = score["accuracy"]
    passed = bool(all(acc.get(k, 0.0) >= ACC_LIMIT for k in GATED))
    now = now or datetime.now()
    decision = {
        "date": now.isoformat(timespec="seconds"),
        "rule": f"vision mode needs >= {ACC_LIMIT:.0%} accuracy on each of {', '.join(GATED)} "
                "(eval/PREREGISTRATION.md); VRAM and latency already passed in Phase 1",
        "n_frames": score["n"],
        "accuracy": {k: round(v, 4) for k, v in acc.items()},
        "client_s": score.get("client_s"),
        "pass": passed,
        "vision_enabled": passed,
        "glasses_source": cap.get("glasses_source"),
        "glasses_for_screen": cap.get("glasses_for_screen"),
        "effect": ("vision mode turns on automatically whenever the Decider runs with -Vision"
                   if passed else "Myrmidon stays text-only; run the Decider in text mode"),
    }
    Path(out_path).write_text(json.dumps(decision, indent=2))
    if spike_results is not None and Path(spike_results).exists():
        update_spike_results(Path(spike_results), decision)
    return decision


def update_spike_results(path: Path, d: dict) -> None:
    src = {"own": "the user's own glasses", "prop": "a prop pair (the user has no glasses of their own)"}.get(
        d.get("glasses_source") or "", "glasses source not recorded")
    accs = ", ".join(f"{k} {v:.1%}" for k, v in d["accuracy"].items())
    p50 = (d.get("client_s") or {}).get("p50")
    block = "\n".join([
        MARK_START,
        f"**S2 re-run, {d['date'][:10]} (guided human session).** {d['n_frames']} labeled frames, {src}. "
        f"Accuracy: {accs} (gate {ACC_LIMIT:.0%} on {' and '.join(GATED)}): **{'PASS' if d['pass'] else 'FAIL'}**."
        + (f" Latency p50 {p50:.2f} s." if p50 else ""),
        "",
        ("Vision mode is now ON whenever the Decider runs with `-Vision` (`results/s2_decision.json`). "
         "The loop sends one webcam frame per tick, with exactly the measured wording, to the local server only."
         if d["pass"] else
         "Myrmidon stays TEXT-ONLY (`results/s2_decision.json`). Glasses off and leaning in are inferred from "
         "distance and squint changes, not seen."),
        MARK_END,
    ])
    text = path.read_text(encoding="utf-8")
    if MARK_START in text and MARK_END in text:
        text = re.sub(re.escape(MARK_START) + r".*?" + re.escape(MARK_END), lambda m: block, text, flags=re.S)
    elif "\n## Notes for the build" in text:
        text = text.replace("\n## Notes for the build", f"\n{block}\n\n## Notes for the build", 1)
    else:
        text = text.rstrip("\n") + f"\n\n{block}\n"
    path.write_text(text, encoding="utf-8")


def cmd_decide(a):
    score = RESULTS / "s2_score.json"
    if not score.exists():
        print("no results/s2_score.json: run `python eval/spike_s2.py score` first")
        return 2
    d = decide_s2(score, RESULTS / "s2_capture.json", RESULTS / "s2_decision.json", SPIKE_RESULTS)
    print(json.dumps(d, indent=2))
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["latency", "capture", "score", "decide"])
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--camera", type=int, default=0)
    ap.add_argument("--baseline-mib", type=int, default=0, help="GPU memory used with no Decider loaded")
    ap.add_argument("--glasses-source", choices=["own", "prop"], default="own",
                    help="capture: the user's own glasses, or any pair used as a prop")
    ap.add_argument("--glasses-for-screen", choices=["yes", "no", "unknown"], default="unknown")
    ap.add_argument("--preview", action="store_true", help="capture: show the camera with the prompt and countdown")
    a = ap.parse_args()
    rc = {"latency": cmd_latency, "capture": cmd_capture, "score": cmd_score, "decide": cmd_decide}[a.mode](a)
    sys.exit(rc or 0)


if __name__ == "__main__":
    main()
