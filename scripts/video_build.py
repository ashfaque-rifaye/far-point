"""Cut the demo video (docs/VIDEO_SCRIPT.md) from the dashboard recordings, animated explainers and narration.

Inputs: <runtime>/recordings/video/dashboard.mp4 + marks.json and dashboard_coach.mp4 + marks_coach.json
from scripts/video_record_scenes.py. Explainers come from scripts/video_scenes.html, drawn frame by frame
in Edge and keyed to the narration. Narration is spoken locally by Kokoro (scripts/video_tts.py, its own
environment). Output: <runtime>/recordings/video/myrmidon-demo.mp4 (1920x1080, 30 fps) and .srt.

    uv run --no-project --with playwright python scripts/video_build.py
"""
import asyncio
import hashlib
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = Path(os.environ.get("MYRMIDON_RUNTIME", r"E:\myrmidon-runtime"))
OUT = RUNTIME / "recordings" / "video"
WORK = OUT / "build"
TTS_PY = RUNTIME / "tts-env" / "Scripts" / "python.exe"
SCENES_HTML = ROOT / "scripts" / "video_scenes.html"
FPS = 30
LEAD_S = 0.3  # silence before each scene's narration
TAIL_S = 0.35  # and after it
REPLAY_BADGE = ("Replay of a synthetic trace through the real agent: Strands Decider 2B on the laptop GPU, "
                "Amazon Nova on Bedrock. Desktop changes are dry-run.")

# A scene is an animated explainer ("explainer": id in video_scenes.html) or dashboard footage ("clip": parts).
# A clip part is (recording, start, end, seconds): recording "v" = dashboard.mp4 in seconds, "m" = a mark in
# it ("name+1.5"), "c" = a mark in dashboard_coach.mp4. Parts with seconds=None share the rest of the scene
# in proportion to their length. A part is sped up (and labelled) or held on its frames to fit.
# The clip windows were picked by looking at the recorded frames.
SCENES = [
    dict(id="hook", title=True, clip=[("v", 0.0, 11.0, None)], lines=[
        "It's late, your glasses are off, and you've crept to twenty-seven centimetres from the screen.",
        "Myrmidon notices, and adapts the screen to your eyes."]),
    dict(id="eyes", explainer="eyes", lines=[
        "It measures on the laptop, from a plain webcam.",
        "MediaPipe finds each iris.",
        "An iris is about eleven point seven millimetres wide in almost everyone, so its width in pixels gives "
        "distance.",
        "A one-time calibration sets your own baseline.",
        "Below it, you're squinting. A short dip is a blink.",
        "Code writes each number as a sentence ending in a verdict."]),
    dict(id="arch", explainer="arch", lines=[
        "Here's the loop, every two and a half seconds.",
        "Strands Decider 2B, on the laptop GPU, reads those sentences and picks the tool.",
        "A Strands agent runs it, guarded by intervention handlers, and the camera checks whether it helped.",
        "Amazon Bedrock handles language: Nova Lite answers only when the Decider is unsure, and writes your "
        "rulebook.",
        "Only text and numbers reach AWS. Never a face."]),
    dict(id="decide", explainer="decide", lines=[
        "The decision handed to Decider 2B is tool selection: which tool, if any, right now?",
        "Each rule becomes a typed yes-or-no question; all of them, plus 'OK to interrupt?', go in one request.",
        "The Decider returns a calibrated probability for each, in about half a second.",
        "Code applies the order: above point six five, a rule fires; below point three five, it's clear; "
        "only in between is Bedrock asked.",
        "Eleven thousand decisions a day, zero cloud tokens."]),
    dict(id="live", clip=[("v", 10.5, 14.0, 2.5), ("v", 14.0, 17.8, None)], lines=[
        "Here it runs on a replayed session, with the real Decider.",
        "At twenty-seven centimetres, rule one fires at point nine seven, and the text grows one step."]),
    dict(id="worked", clip=[("v", 17.8, 44.8, 2.0), ("v", 44.8, 46.2, None)], lines=[
        "Thirty seconds later, the camera checks: forty-five centimetres. It worked."]),
    dict(id="deny", clip=[("v", 103.0, 113.0, None), ("v", 130.5, 135.5, None), ("v", 160.0, 199.0, None)], lines=[
        "On a Teams call, a break comes due.",
        "The Interrupt Gate reads the Decider's interrupt answer, point one eight, and holds it.",
        "After the call, the break counts only when the camera sees you look away."]),
    dict(id="coach", clip=[("c", "rules", "rules_adopted+2.5", None), ("c", "report_ask", "end", None)], lines=[
        "Nova turns your own words into the rulebook the Decider reads, and writes a numbers-only report."]),
    dict(id="results", explainer="results", lines=[
        "Measured on seventy-two preregistered test states:",
        "one nine-way question, sixty-eight percent. One question per rule, eighty-seven and a half. "
        "With Bedrock on unsure rules, one hundred.",
        "Nova Lite alone matched it, but took two and a half seconds, with eleven times the tokens.",
        "Lesson: code does the arithmetic; the Decider answers one clear question at a time."]),
    dict(id="pattern", explainer="pattern", lines=[
        "The reusable piece is Reflex Gate.",
        "Typed questions, a confidence policy, and an Interrupt Gate you drop into any Strands agent as an "
        "intervention handler.",
        "A posture coach reuses it with no eye code."]),
    dict(id="end", explainer="end", min=7.0, lines=[
        "Myrmidon: tool selection with Strands Decider 2B and Amazon Bedrock. Open source, ready to reuse."]),
]

BADGE_HTML = """<!doctype html><html><head><meta charset="utf-8"><style>
html,body{margin:0;background:transparent}
span{display:inline-block;font:600 19px 'Segoe UI',Arial,sans-serif;color:#fff;background:rgba(7,13,24,.82);
border:1px solid rgba(255,255,255,.22);border-radius:999px;padding:9px 18px;white-space:nowrap}
b{color:#36dccd}</style></head><body><span>%s</span></body></html>"""

TITLE_HTML = """<!doctype html><html><head><meta charset="utf-8"><style>
html,body{margin:0;background:transparent}
div{display:inline-flex;align-items:center;gap:22px;padding:22px 34px 22px 24px;border-radius:28px;
background:rgba(7,13,24,.86);border:1px solid rgba(255,255,255,.18);font-family:'Segoe UI',Arial,sans-serif;color:#e9effa}
b{font-size:58px;letter-spacing:-1.5px;display:block;line-height:1}
i{font-style:normal;font-size:22px;color:#9fb0cc;display:block;margin-top:8px}</style></head><body><div>
<svg width="74" height="74" viewBox="0 0 64 64"><defs><linearGradient id="l" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#2fd3c4"/><stop offset="1" stop-color="#3b6cf6"/></linearGradient></defs><rect width="64" height="64" rx="20" fill="#e9effa"/><circle cx="32" cy="32" r="16" fill="none" stroke="url(#l)" stroke-width="5"/><circle cx="32" cy="32" r="6" fill="url(#l)"/></svg>
<span><b>Myrmidon</b><i>Strands Decider 2B decides on the laptop · Amazon Bedrock writes the words</i></span></div></body></html>"""


def ff(*args: str, cwd: Path | None = None) -> None:
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], check=True, cwd=cwd)


def probe_len(path: Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                       capture_output=True, text=True, check=True)
    return float(r.stdout.strip())


def speak() -> dict:
    spec = [{"id": s["id"], "lines": s["lines"]} for s in SCENES if s["lines"]]
    blob = json.dumps(spec, sort_keys=True).encode()
    tts = WORK / "tts"
    stamp = tts / "spec.sha"
    digest = hashlib.sha256(blob + (ROOT / "scripts" / "video_tts.py").read_bytes()).hexdigest()
    if not (stamp.exists() and stamp.read_text() == digest):
        tts.mkdir(parents=True, exist_ok=True)
        (tts / "narration.json").write_bytes(blob)
        env = dict(os.environ, HF_HOME=str(RUNTIME / "hf"), HF_HUB_DISABLE_SYMLINKS_WARNING="1")
        subprocess.run([str(TTS_PY), str(ROOT / "scripts" / "video_tts.py"), str(tts / "narration.json"), str(tts)],
                       check=True, env=env)
        stamp.write_text(digest)
    return json.loads((tts / "timings.json").read_text(encoding="utf-8"))


def duration(s: dict, cues: list) -> float:
    voice = cues[-1][1] if cues else 0.0
    return round(max(s.get("min", 0.0), LEAD_S + voice + TAIL_S), 3)


async def render_overlays_and_explainers(durs: dict, timings: dict) -> None:
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="msedge")
        badge = await browser.new_page(viewport={"width": 1900, "height": 200})
        for name, text in [("replay", REPLAY_BADGE)] + [(f"x{n}", f"<b>{n}× speed</b>") for n in range(2, 13)]:
            await badge.set_content(BADGE_HTML % text)
            await badge.locator("span").screenshot(path=str(WORK / f"badge_{name}.png"), omit_background=True)
        await badge.set_content(TITLE_HTML)
        await badge.locator("div").screenshot(path=str(WORK / "title.png"), omit_background=True)

        page = await browser.new_page(viewport={"width": 1920, "height": 1080})
        for s in SCENES:
            if "explainer" not in s:
                continue
            dur, cues = durs[s["id"]], timings.get(s["id"], [])
            out = WORK / f"anim_{s['id']}.mp4"
            stamp = WORK / f"anim_{s['id']}.sha"
            digest = hashlib.sha256(SCENES_HTML.read_bytes() + json.dumps([dur, cues]).encode()).hexdigest()
            if out.exists() and stamp.exists() and stamp.read_text() == digest:
                continue
            await page.goto(f"{SCENES_HTML.as_uri()}?scene={s['explainer']}")
            await page.evaluate("o => setup(o)", {"dur": dur, "lead": LEAD_S, "cues": cues})
            enc = subprocess.Popen(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "image2pipe",
                                    "-framerate", str(FPS), "-i", "-", "-c:v", "libx264", "-crf", "16",
                                    "-preset", "medium", "-pix_fmt", "yuv420p", str(out)], stdin=subprocess.PIPE)
            for i in range(int(round(dur * FPS))):
                await page.evaluate(f"render({i / FPS:.4f})")
                enc.stdin.write(await page.screenshot(type="jpeg", quality=92))
            enc.stdin.close()
            enc.wait()
            stamp.write_text(digest)
            print(f"{s['id']:8s} animated {dur:.1f} s")
        await browser.close()


def resolve(rec: str, ref, marks: dict) -> float:
    if rec == "v":
        return float(ref)
    name, _, plus = str(ref).partition("+")
    return marks[name] + (float(plus) if plus else 0.0)


def plan_parts(parts, dur: float, recordings: dict) -> list[tuple]:
    """-> [(src, start, end, out_seconds)] filling exactly dur seconds."""
    spans = []
    for rec, a, b, secs in parts:
        src, marks = recordings[rec]
        spans.append((src, resolve(rec, a, marks), resolve(rec, b, marks), secs))
    fixed = sum(s[3] for s in spans if s[3])
    free = sum(s[2] - s[1] for s in spans if not s[3])
    return [(src, a, b, secs if secs else (dur - fixed) * (b - a) / free) for src, a, b, secs in spans]


def chunk_captions(cues: list, offset: float) -> list[tuple[float, float, str]]:
    """Sentences -> subtitle events of at most two lines of 42 characters, timed by character share."""
    events = []
    for c0, c1, text in cues:
        words, chunks, cur = text.split(), [], ""
        for w in words:
            nxt = f"{cur} {w}".strip()
            if len(nxt) > 78 or (len(cur) > 40 and cur.endswith((",", ";", ":"))):
                chunks.append(cur)
                cur = w
            else:
                cur = nxt
        chunks.append(cur)
        total = sum(len(x) for x in chunks)
        t = c0
        for x in chunks:
            d = (c1 - c0) * len(x) / total
            events.append((offset + t, offset + t + d, two_lines(x)))
            t += d
    return events


def two_lines(text: str) -> str:
    if len(text) <= 42:
        return text
    words = text.split()
    best, cut = None, 1
    for i in range(1, len(words)):
        a, b = " ".join(words[:i]), " ".join(words[i:])
        # balanced and bottom-heavy, like broadcast subtitles; over-long lines cost the most
        score = 10 * max(0, max(len(a), len(b)) - 42) + abs(len(a) - len(b)) + (0 if len(b) >= len(a) else 3)
        if best is None or score < best:
            best, cut = score, i
    return " ".join(words[:cut]) + "\\N" + " ".join(words[cut:])


def ass_time(x: float) -> str:
    cs = int(round(x * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def srt_time(x: float) -> str:
    ms = int(round(x * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def write_captions(events: list) -> None:
    # White text, thin black outline and a soft shadow, no box: the streaming-service look.
    head = ("[Script Info]\nScriptType: v4.00+\nPlayResX: 1920\nPlayResY: 1080\nWrapStyle: 2\nScaledBorderAndShadow: yes\n\n"
            "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
            "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
            "Alignment, MarginL, MarginR, MarginV, Encoding\n"
            "Style: Default,Segoe UI Semibold,52,&H00FFFFFF,&H000000FF,&H00000000,&H78000000,0,0,0,0,100,100,0.3,0,"
            "1,2.4,1.6,2,120,120,58,1\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, "
            "Effect, Text\n")
    body = "".join(f"Dialogue: 0,{ass_time(a)},{ass_time(b)},Default,,0,0,0,,{t}\n" for a, b, t in events)
    (WORK / "captions.ass").write_text(head + body, encoding="utf-8")
    (OUT / "myrmidon-demo.srt").write_text(
        "\n".join(f"{i}\n{srt_time(a)} --> {srt_time(b)}\n{t.replace(chr(92) + 'N', chr(10))}\n"
                  for i, (a, b, t) in enumerate(events, 1)), encoding="utf-8")


def render_clip(s: dict, dur: float, seg: Path, audio: list, afilt: str, recordings: dict) -> str:
    parts = plan_parts(s["clip"], dur, recordings)
    inputs, chains, overlays, t = [], [], [], 0.0
    for i, (src, a, b, secs) in enumerate(parts):
        inputs += ["-ss", f"{a:.3f}", "-t", f"{b - a:.3f}", "-i", str(src)]
        speed = (b - a) / secs
        chains.append(f"[{i}:v]setpts=(PTS-STARTPTS)/{speed:.4f},fps={FPS},tpad=stop_mode=clone:stop_duration=4,"
                      f"trim=duration={secs:.3f},setpts=PTS-STARTPTS[p{i}]")
        if speed >= 1.5:
            overlays.append((f"badge_x{min(12, max(2, round(speed)))}.png", t, t + secs))
        t += secs
    n = len(parts)
    inputs += audio
    extra = [WORK / "badge_replay.png"] + [WORK / o[0] for o in overlays] + ([WORK / "title.png"] if s.get("title") else [])
    for p in extra:
        inputs += ["-loop", "1", "-i", str(p)]
    k = n + 1  # first overlay input index
    vf = ";".join(chains) + ";" + "".join(f"[p{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=0[c0]"
    vf += f";[c0][{k}:v]overlay=W-w-22:18:shortest=1[c1]"
    last = "c1"
    for j, (_, t0, t1) in enumerate(overlays):
        vf += f";[{last}][{k + 1 + j}:v]overlay=22:18:shortest=1:enable='between(t,{t0:.2f},{t1:.2f})'[o{j}]"
        last = f"o{j}"
    if s.get("title"):
        vf += f";[{last}][{k + 1 + len(overlays)}:v]overlay=60:H-h-300:shortest=1[tt]"  # clear of the captions
        last = "tt"
    vf += f";[{last}]trim=duration={dur},format=yuv420p[v]"
    ff(*inputs, "-filter_complex", vf + ";" + afilt.replace("[1:a]", f"[{n}:a]"), "-map", "[v]", "-map", "[a]",
       "-t", str(dur), "-c:v", "libx264", "-crf", "17", "-preset", "medium", "-r", str(FPS),
       "-c:a", "aac", "-b:a", "192k", str(seg))
    return " + ".join(f"{a:.1f}-{b:.1f}s x{(b - a) / secs:.2f}" for _, a, b, secs in parts)


def build() -> None:
    WORK.mkdir(parents=True, exist_ok=True)
    recordings = {"v": (OUT / "dashboard.mp4", json.loads((OUT / "marks.json").read_text()))}
    recordings["m"] = recordings["v"]
    # the full take films the coach scenes too; a --coach-only retake replaces them when present
    coach = OUT / "dashboard_coach.mp4"
    recordings["c"] = ((coach, json.loads((OUT / "marks_coach.json").read_text())) if coach.exists()
                       else recordings["v"])
    timings = speak()
    durs = {s["id"]: duration(s, timings.get(s["id"], [])) for s in SCENES}
    asyncio.run(render_overlays_and_explainers(durs, timings))
    segs, events, clock = [], [], 0.0
    for s in SCENES:
        sid, dur = s["id"], durs[s["id"]]
        cues = timings.get(sid, [])
        seg = WORK / f"seg_{sid}.mp4"
        audio = ["-i", str(WORK / "tts" / f"{sid}.wav")]
        afilt = (f"[1:a]adelay={int(LEAD_S * 1000)},apad,atrim=0:{dur},aresample=48000,"
                 f"aformat=channel_layouts=stereo[a]")
        if "clip" in s:
            how = render_clip(s, dur, seg, audio, afilt, recordings)
            print(f"{sid:8s} clip {how} -> {dur:.1f} s")
        else:
            ff("-i", str(WORK / f"anim_{sid}.mp4"), *audio, "-filter_complex",
               f"[0:v]tpad=stop_mode=clone:stop_duration=2,trim=duration={dur},format=yuv420p[v];" + afilt,
               "-map", "[v]", "-map", "[a]", "-t", str(dur), "-c:v", "libx264", "-crf", "17", "-preset", "medium",
               "-r", str(FPS), "-c:a", "aac", "-b:a", "192k", str(seg))
            print(f"{sid:8s} explainer -> {dur:.1f} s")
        events += chunk_captions(cues, clock + LEAD_S)
        segs.append(seg)
        clock += dur
    write_captions(events)
    (WORK / "segs.txt").write_text("".join(f"file '{p.name}'\n" for p in segs), encoding="utf-8")
    final = OUT / "myrmidon-demo.mp4"
    ff("-f", "concat", "-safe", "0", "-i", "segs.txt", "-vf", "ass=captions.ass",
       "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-c:v", "libx264", "-crf", "18", "-preset", "slow",
       "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
       str(final), cwd=WORK)
    print(f"saved {final}  {probe_len(final):.1f} s")


if __name__ == "__main__":
    build()
