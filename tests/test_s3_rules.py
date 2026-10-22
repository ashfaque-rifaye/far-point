import sys
from pathlib import Path

from strands_decider.schema import SystemOneRequest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "eval"))

from s1_states import PRIORITY, Facts, generate, render, triggers  # noqa: E402
from s3_rules import RULES_NEW, RULES_OLD, reference, render_s3  # noqa: E402

from patterns.reflex_gate import build_questions  # noqa: E402

# rule -> (line prefix, ending when the rule holds)
LINES = {"ask_user": ("- Squint check:", ": asking needed."),
         "glasses_reminder": ("- Glasses:", ": glasses reminder needed."),
         "enlarge_text": ("- Text size:", ": enlarging needed."),
         "dark_mode": ("- Theme:", ", dark mode needed."),
         "dim_screen": ("- Screen brightness:", ": dimming needed."),
         "brighten_screen": ("- Screen brightness:", ": brightening needed."),
         "far_look_break": ("- Continuous near work:", ": break is due."),
         "reduce_text": ("- Text enlarged earlier:", ": text can go back to default.")}


def test_every_s3_rule_validates_through_the_decider_schema():
    for rules in (RULES_NEW, RULES_OLD):
        req = SystemOneRequest(state=render_s3(Facts(**generate(4)[0]["facts"])), questions=build_questions(rules))
        assert len(req.questions) == 9


def test_reference_labels_equal_s1_triggers_on_seed_4():
    for it in generate(4):
        f = Facts(**it["facts"])
        ref = reference(f)
        assert [t for t in PRIORITY if ref[t]] == triggers(f) == it["triggers"]


def test_new_render_verdict_phrases_match_labels_and_old_render_is_s1():
    for seed in (3, 4):
        for it in generate(seed):
            f = Facts(**it["facts"])
            text, ref = render_s3(f), reference(f)
            lines = text.splitlines()
            for tool, (prefix, ending) in LINES.items():
                line = next(ln for ln in lines if ln.startswith(prefix))
                assert line.endswith(ending) == ref[tool], (tool, line)
            assert "balanced" not in text
            assert render(f) == it["state"]  # the ablation text is S1's, unchanged
