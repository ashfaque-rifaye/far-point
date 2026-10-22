import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "eval"))

from s1_states import ACTIONS, PRIORITY, generate  # noqa: E402


def test_generate_is_deterministic_and_balanced():
    a, b = generate(1), generate(1)
    assert [x["state"] for x in a] == [x["state"] for x in b]
    assert len(a) >= 60
    assert Counter(x["labels"]["next_action"] for x in a) == {k: 8 for k in ACTIONS}


def test_label_is_highest_priority_trigger():
    for x in generate(2):
        t = x["triggers"]
        assert x["labels"]["next_action"] == (t[0] if t else "none")
        assert t == sorted(t, key=PRIORITY.index)
