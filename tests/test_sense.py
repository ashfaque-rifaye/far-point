from farpoint.sense import distance_cm, focal_length_px


def test_distance_roundtrip():
    f = focal_length_px(iris_px=20.0, distance_cm=50.0)
    assert abs(distance_cm(20.0, f) - 50.0) < 1e-9
    # Half the iris size means twice as far.
    assert abs(distance_cm(10.0, f) - 100.0) < 1e-9
