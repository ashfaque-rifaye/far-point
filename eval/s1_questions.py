"""Decider question sets for spike S1. v1 is the first wording; v2 exists only if a retune is needed."""
from __future__ import annotations

V1 = {
    "next_action": {
        "type": "choice",
        "instructions": (
            "Choose Myrmidon's single next action for this user, following the doctrine. "
            "When several actions apply, pick the one that comes first in the doctrine's priority order."
        ),
        "criteria": {
            "none": "Every measured fact is within the doctrine; nothing needs to change.",
            "enlarge_text": "Text is below the comfortable minimum size and the user is squinting or too close.",
            "reduce_text": "Text was enlarged earlier, and the user is now relaxed at a comfortable distance and not squinting, so text can go back to default.",
            "dim_screen": "The room is dark, the theme is already dark, and the screen is much brighter than the room.",
            "brighten_screen": "The room is bright and the screen is much dimmer than the room.",
            "dark_mode": "The room is dark and the theme is light.",
            "far_look_break": "Continuous near work has reached the 20-minute far-look break.",
            "glasses_reminder": "Glasses are prescribed for screen work and the user is not wearing them.",
            "ask_user": "The user keeps squinting even though glasses are on (or none are prescribed) and text is already large; ask how their eyes feel.",
        },
    },
    "strain": {
        "type": "score",
        "instructions": (
            "How much visual strain does the user show right now? Strain signs are: squinting, "
            "too close, far-look break due, low blink rate."
        ),
        "criteria": [
            "relaxed: no strain signs",
            "mild: exactly one strain sign",
            "strong: two or more strain signs",
        ],
    },
    "interrupt_ok": {
        "type": "noul",
        "instructions": "Is this an OK moment to interrupt the user with a prompt?",
        "criteria": {
            "true": "a natural pause: the user is idle, between tasks, or just switched windows",
            "false": "the user is in a video call, presenting or screen sharing, typing in a burst, or watching fullscreen video",
        },
    },
}

# v2: the one retune allowed by the preregistration, written after reading the run-1
# confusion matrix. Changes: options listed in doctrine priority order, each criterion
# quotes the rendered wording and names what it outranks, and strain / interrupt_ok get
# explicit criteria that point at the line to read.
V2 = {
    "next_action": {
        "type": "choice",
        "instructions": (
            "Pick Myrmidon's next action. Check the options from first to last and pick the "
            "FIRST one whose condition holds in the measured facts."
        ),
        "criteria": {
            "ask_user": "Eyes: squinting, AND Text size: large, AND glasses are on or none are prescribed. Outranks every other option.",
            "glasses_reminder": "Glasses: off, while glasses are prescribed for screen work. Outranks every option below.",
            "enlarge_text": "Text size: small, AND (Eyes: squinting OR Viewing distance: too close). Outranks every option below.",
            "dark_mode": "Room light: dark, AND Theme: light. Outranks every option below.",
            "dim_screen": "Room light: dark, AND Theme: dark, AND the screen is much brighter than the room. Outranks every option below.",
            "brighten_screen": "The screen is much dimmer than the room. Outranks every option below.",
            "far_look_break": "Continuous near work: break is due, and no option above holds. Outranks reduce_text.",
            "reduce_text": "Text was enlarged earlier: yes, and no option above holds.",
            "none": "No option above holds: glasses fine, text not small, theme and brightness suit the room, break not due, text not enlarged earlier.",
        },
    },
    "strain": {
        "type": "score",
        "instructions": (
            "Count the strain signs in the measured facts: Eyes: squinting; Viewing distance: too close; "
            "break is due; Blink rate: low."
        ),
        "criteria": [
            "relaxed: none of the four strain signs",
            "mild: exactly one of the four strain signs",
            "strong: two or more of the four strain signs",
        ],
    },
    "interrupt_ok": {
        "type": "noul",
        "instructions": "Read the Activity line. Is it OK to interrupt the user with a prompt right now?",
        "criteria": {
            "true": "Activity says idle, between tasks, or just switched windows",
            "false": "Activity says video call, presenting or screen sharing, typing in a burst, or fullscreen video",
        },
    },
}

VERSIONS = {"v1": V1, "v2": V2}
