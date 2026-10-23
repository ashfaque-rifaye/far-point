"""Optional vision mode: one webcam frame to the LOCAL Decider. Off by default.

`S2_STATE`, `S2_QUESTIONS` and `GATED` are the exact request measured in spike S2
(`eval/spike_s2.py` imports them from here), so the loop asks exactly what was measured,
over one webcam frame, in a request of its own. Screen images are never sent, and Bedrock
never receives any image.

Vision turns on automatically only when BOTH hold:
- `results/s2_decision.json` records an S2 pass (both gated questions >= 85% accuracy), and
- the local Decider server runs with `--vision` (its /health says `"vision": true`).
`--vision` / `MYRMIDON_VISION=1` force it on; `--no-vision` / `MYRMIDON_VISION=0` force it off.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
S2_DECISION_PATH = ROOT / "results" / "s2_decision.json"

S2_STATE = "Webcam frame of the user at their laptop. The camera sits at the top edge of the screen."
S2_QUESTIONS = {
    "glasses_on": {
        "type": "noul",
        "instructions": "Is the person in the image wearing glasses on their face?",
        "criteria": {
            "true": "eyeglass frames or lenses are visible on the person's face, in front of the eyes",
            "false": "no glasses on the face; glasses held in a hand or absent count as false",
        },
    },
    "rubbing_eyes": {
        "type": "noul",
        "instructions": "Is the person rubbing or touching their eyes?",
        "criteria": {
            "true": "a hand or fingers touch or cover one or both eyes",
            "false": "hands are away from the eyes",
        },
    },
    "looking_far_away": {
        "type": "noul",
        "instructions": "Is the person looking far away from the screen?",
        "criteria": {
            "true": "head and gaze are turned away from the screen toward a distant point, such as across the room or out of a window",
            "false": "the person is looking at the screen or the camera",
        },
    },
}
GATED = ("glasses_on", "looking_far_away")

# Not measured by S2 and not used by any rule: reported in `answers.vision.video_call` only.
VIDEO_CALL = {
    "type": "noul",
    "instructions": "Does the person look like they are on a video call, for example wearing a headset or talking toward the screen?",
    "criteria": {
        "true": "a headset or earbuds are visible, or the person is visibly talking toward the screen",
        "false": "no headset, and the person is quietly reading or working",
    },
}

# Decider question name -> contract key in `decision.answers.vision`.
CONTRACT_KEYS = {"glasses_on": "glasses_on", "rubbing_eyes": "rubbing_eyes", "looking_far_away": "looking_far",
                 "video_call": "video_call"}
FRESH_S = 10.0  # a vision answer older than this is ignored


def vision_questions() -> dict:
    return {**{k: dict(v, criteria=dict(v["criteria"])) for k, v in S2_QUESTIONS.items()}, "video_call": VIDEO_CALL}


def tri(p: float | None, fire_p: float = 0.65, clear_p: float = 0.35) -> bool | None:
    """True / False / None (unsure) from a noul probability, with the policy's thresholds."""
    if p is None:
        return None
    if p >= fire_p:
        return True
    if p <= clear_p:
        return False
    return None


def s2_decision(path: Path = S2_DECISION_PATH) -> dict | None:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def s2_allows_vision(path: Path = S2_DECISION_PATH) -> bool:
    d = s2_decision(path)
    return bool(d and d.get("pass") is True and d.get("vision_enabled") is True)


def resolve_vision(requested: bool | None, health_info: dict | None, decision_path: Path = S2_DECISION_PATH) -> tuple[bool, str]:
    """(vision on?, why). `requested` is the CLI/env choice; None means automatic."""
    if requested is True:
        return True, "forced on (--vision or MYRMIDON_VISION=1)"
    if requested is False:
        return False, "forced off (--no-vision or MYRMIDON_VISION=0)"
    if not s2_allows_vision(decision_path):
        return False, "text-only: S2 has not passed (results/s2_decision.json)"
    if not (health_info and health_info.get("vision")):
        return False, "text-only: S2 passed, but the Decider server does not run with --vision"
    return True, "on: S2 passed and the Decider server runs with --vision"
