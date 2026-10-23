from myrmidon.doctrine import Profile, default_doctrine
from myrmidon.facts import Facts, render_state, strain
from myrmidon.predicates import PREDICATES


def base(**kw) -> Facts:
    f = Facts(face=True, distance_cm=52, squint_ratio=0.97, blink_per_min=15, usual_distance_cm=55,
              room="normal", brightness_pct=60, theme="light", app_name="Acrobat Reader", app_category="pdf",
              zoom_available=True, activity="idle for 30 s (foreground: Acrobat Reader)")
    for k, v in kw.items():
        setattr(f, k, v)
    return f


def test_dark_room_light_theme_renders_mismatch_not_balanced():
    d = default_doctrine()
    text = render_state(base(room="dark", theme="light", brightness_pct=40), d)
    assert "Theme: light, in a dark room: mismatch, dark mode needed." in text
    assert "balanced" not in text
    assert "Room light: dark (estimated from camera brightness)." in text
    assert PREDICATES["dark_mode"](base(room="dark", theme="light"), d.limits)
    assert "Theme: dark: no change needed." in render_state(base(room="dark", theme="dark"), d)


def test_distance_lines():
    d = default_doctrine()
    assert "too close, enlarging needed." in render_state(base(distance_cm=27, under_near_s=8), d)
    t = render_state(base(distance_cm=27, under_near_s=8, zoom_available=False), d)
    assert "too close, but this app has no zoom control." in t
    t = render_state(base(distance_cm=27, under_near_s=3), d)
    assert "no enlarging needed yet." in t and "too close" not in t
    assert "- Viewing distance: 52 cm: no enlarging needed." in render_state(base(distance_cm=52), d)
    assert "no face visible" in render_state(base(face=False, distance_cm=None), d)


def test_local_time_line():
    d = default_doctrine()
    assert "- Local time: 22:40 (night)." in render_state(base(local_time="22:40"), d)
    assert "- Local time: 09:05 (morning)." in render_state(base(local_time="09:05"), d)
    assert "Local time" not in render_state(base(), d)


def test_relaxed_reading_line():
    d = default_doctrine()
    assert "Myrmidon zoom +1: text can go back one step." in render_state(base(zoom_step=1, relaxed_min_now=11), d)
    assert "Myrmidon zoom +0: no change needed." in render_state(base(zoom_step=0, relaxed_min_now=11), d)


def test_brightness_and_glasses_lines():
    d = default_doctrine()
    assert "85%: dimming needed (too bright for a dark room)." in render_state(
        base(room="dark", theme="dark", brightness_pct=85), d)
    assert "20%: brightening needed (too dim for a bright room)." in render_state(base(room="bright", brightness_pct=20), d)
    assert "55%: no change needed." in render_state(base(room="dark", theme="dark", brightness_pct=55), d)
    assert "not adjustable on this display" in render_state(base(brightness_pct=None), d)
    t = render_state(base(distance_cm=44, squinting=True, squinting_s=9, squint_ratio=0.68, glasses_off_signs=True), d)
    assert "worn: not checked (text-only mode)" in t
    assert "signs consistent with glasses off: yes (leaning in 11 cm closer than your usual 55 cm, and squinting)" in t
    assert t.count("no reminder needed") == 1  # prescription unknown -> no reminder


def test_glasses_line_follows_profile():
    d = default_doctrine().model_copy(update={"profile": Profile(glasses_for_screen="yes", conditions=["myopia"])})
    t = render_state(base(), d)
    assert "Glasses: prescribed for screen work: yes;" in t and "Profile (user's own words): myopia." in t
    t2 = render_state(base(distance_cm=44, squinting=True, squint_ratio=0.68, glasses_off_signs=True), d)
    assert t2.split("- Glasses:")[1].split("\n")[0].endswith(": reminder due.")


def test_strain_levels_counted_in_code():
    L = default_doctrine().limits
    assert strain(base(), L)["level"] == "relaxed"
    one = strain(base(squinting=True), L)
    assert one["level"] == "mild" and one["expected"] == 1.0 and one["probs"]["mild"] == 1.0
    two = strain(base(squinting=True, distance_cm=25, under_near_s=9), L)
    assert two["level"] == "strong" and two["expected"] == 2.0
    four = strain(base(squinting=True, distance_cm=25, under_near_s=9, bout_min_now=50, blink_per_min=6), L)
    assert four["level"] == "strong" and four["signs"] == 4


def test_predicates_cover_default_rules():
    L = default_doctrine().limits
    assert PREDICATES["enlarge_text"](base(distance_cm=27, under_near_s=8), L)
    assert not PREDICATES["enlarge_text"](base(distance_cm=27, under_near_s=8, zoom_available=False), L)
    assert PREDICATES["far_look_break"](base(bout_min_now=46), L)
    assert PREDICATES["reduce_text"](base(zoom_step=1, relaxed_min_now=11), L)
    assert PREDICATES["ask_user"](base(squinting=True, squinting_s=70, zoom_step=2), L)
    assert not PREDICATES["glasses_reminder"](base(glasses_off_signs=True), L)
    assert PREDICATES["glasses_reminder"](base(glasses_off_signs=True, glasses_prescribed="yes"), L)
