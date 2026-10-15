from app.lpp import extract


def test_gps_and_sensors_are_split():
    fix, readings = extract([
        {"channel": 1, "type": "gps", "value": {"latitude": 47.3769, "longitude": 8.5417, "altitude": 410.5}},
        {"channel": 2, "type": "voltage", "value": 4.05},
        {"channel": 3, "type": "accelerometer", "value": {"acc_x": 0.1, "acc_y": 0.0, "acc_z": 1.0}},
    ])
    assert (fix.lat, fix.lon, fix.alt) == (47.3769, 8.5417, 410.5)
    assert [(r.type, r.value) for r in readings] == [
        ("voltage", 4.05), ("accelerometer.acc_x", 0.1), ("accelerometer.acc_y", 0.0), ("accelerometer.acc_z", 1.0)]


def test_zero_zero_and_out_of_range_are_no_fix():
    assert extract([{"channel": 1, "type": "gps", "value": {"latitude": 0.0, "longitude": 0.0, "altitude": 0}}])[0] is None
    assert extract([{"channel": 1, "type": "gps", "value": {"latitude": 95.0, "longitude": 8.0, "altitude": 0}}])[0] is None


def test_empty_and_garbage():
    assert extract(None) == (None, [])
    assert extract([]) == (None, [])
    assert extract(["x", {"type": "gps", "value": "kaputt"}]) == (None, [])


def test_real_library_output_roundtrip():
    """Format der meshcore-Bibliothek: dekodierte Cayenne-LPP-Frames."""
    from cayennelpp import LppFrame
    from meshcore.parsing import lpp_parse

    frame = LppFrame()
    frame.add_gps(1, 47.3769, 8.5417, 410.5)
    frame.add_voltage(2, 4.05)
    frame.add_temperature(3, 21.5)
    fix, readings = extract(lpp_parse(bytes(frame)))
    assert abs(fix.lat - 47.3769) < 1e-4 and abs(fix.lon - 8.5417) < 1e-4
    assert {r.type for r in readings} == {"voltage", "temperature"}
