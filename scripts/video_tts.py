"""Speak the demo-video narration with Kokoro (local, Apache-2.0) into one WAV per scene.

Reads a JSON list of {"id", "lines": [sentence, ...]} and writes <out>/<id>.wav plus timings.json
(start and end of every sentence, for the captions). Runs in its own environment so torch never
enters the agent's requirements:

    E:\\farpoint-runtime\\tts-env\\Scripts\\python.exe scripts/video_tts.py narration.json out_dir
"""
import json
import sys
from pathlib import Path

import numpy as np
import soundfile as sf
from kokoro import KPipeline

RATE = 24000
GAP_S = 0.28  # pause between sentences
VOICE = "af_heart"


def main(spec_path: str, out_dir: str) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    pipe = KPipeline(lang_code="a", repo_id="hexgrad/Kokoro-82M")
    timings = {}
    for scene in json.loads(Path(spec_path).read_text(encoding="utf-8-sig")):
        parts, cues, t = [], [], 0.0
        for line in scene["lines"]:
            audio = np.concatenate([np.asarray(a) for _, _, a in pipe(line, voice=VOICE, speed=1.0, split_pattern=None)])
            cues.append([round(t, 3), round(t + len(audio) / RATE, 3), line])
            parts += [audio, np.zeros(int(GAP_S * RATE), dtype=np.float32)]
            t += len(audio) / RATE + GAP_S
        sf.write(out / f"{scene['id']}.wav", np.concatenate(parts[:-1]), RATE)
        timings[scene["id"]] = cues
        print(f"{scene['id']}: {cues[-1][1]:.1f} s", flush=True)
    (out / "timings.json").write_text(json.dumps(timings, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
