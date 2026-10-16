import dataclasses
import time

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.sim import SIM_KEY, SimLink

KEY = "ab" * 32


def client(tmp_path, **kw):
    s = dataclasses.replace(Settings(), transport="sim", db_path=str(tmp_path / "a.db"),
                            min_spacing=0, flood_backoff=0, **kw)
    return TestClient(create_app(s, SimLink(seed=1, path_breaks_after=99)))


def test_sim_seeds_tracker_and_poll_flow(tmp_path):
    with client(tmp_path) as c:
        trackers = c.get("/api/trackers").json()
        assert len(trackers) == 1 and trackers[0]["public_key"] == SIM_KEY
        tid = trackers[0]["id"]
        assert c.post(f"/api/trackers/{tid}/poll").status_code == 202
        for _ in range(60):
            t = c.get("/api/trackers").json()[0]
            if t["last_poll"]:
                break
            time.sleep(0.2)
        assert t["fix"]["source"] == "telemetry"
        assert t["last_poll"]["ok"] == 1
        assert c.get(f"/api/trackers/{tid}/track").json()[0]["lat"] > 47
        gpx = c.get(f"/api/trackers/{tid}/export.gpx")
        assert gpx.status_code == 200 and "<trkpt" in gpx.text
        assert c.get("/api/status").json()["connected"] is True


def test_validation_and_crud(tmp_path):
    with client(tmp_path) as c:
        bad = c.post("/api/trackers", json={"name": "x", "public_key": "zz"})
        assert bad.status_code == 422
        ok = c.post("/api/trackers", json={"name": " Zweiter ", "public_key": "CD" * 32, "interval_min": 5})
        assert ok.status_code == 201 and ok.json()["public_key"] == "cd" * 32 and ok.json()["name"] == "Zweiter"
        assert c.post("/api/trackers", json={"name": "d", "public_key": "cd" * 32}).status_code == 409
        tid = ok.json()["id"]
        p = c.patch(f"/api/trackers/{tid}", json={"interval_min": 15, "route_mode": "flood", "enabled": False})
        assert p.json()["interval_min"] == 15 and p.json()["route_mode"] == "flood" and p.json()["enabled"] is False
        assert c.patch(f"/api/trackers/{tid}", json={"route_mode": "quatsch"}).status_code == 422
        assert c.delete(f"/api/trackers/{tid}").status_code == 204
        assert c.get(f"/api/trackers/{tid}/track").status_code == 404


def test_reset_path_endpoint(tmp_path):
    with client(tmp_path) as c:
        tid = c.get("/api/trackers").json()[0]["id"]
        assert c.post(f"/api/trackers/{tid}/reset-path").json() == {"ok": True}
        assert c.get("/api/trackers").json()[0]["route_now"] == "flood"


def test_contacts_listing(tmp_path):
    with client(tmp_path) as c:
        contacts = c.get("/api/contacts").json()
        assert contacts[0]["name"] == "Sim-Tracker" and contacts[0]["tracked"] is True


def test_basic_auth(tmp_path):
    with client(tmp_path, auth_user="u", auth_password="p") as c:
        assert c.get("/api/status").status_code == 401
        assert c.get("/healthz").status_code == 200
        assert c.get("/api/status", auth=("u", "p")).status_code == 200
        assert c.get("/api/status", auth=("u", "falsch")).status_code == 401


def test_config_exposes_tile_settings(tmp_path):
    with client(tmp_path, tile_url="https://tiles.example/{z}/{x}/{y}.png", tile_max_zoom=17) as c:
        cfg = c.get("/api/config").json()
        assert cfg["tile_url"] == "https://tiles.example/{z}/{x}/{y}.png" and cfg["tile_max_zoom"] == 17
    with client(tmp_path) as c:
        assert "openstreetmap" in c.get("/api/config").json()["tile_url"]


def test_static_index_served(tmp_path):
    with client(tmp_path) as c:
        r = c.get("/")
        assert r.status_code == 200 and "MeshTracker" in r.text
        assert c.get("/vendor/leaflet/leaflet.js").status_code == 200


def test_series_endpoint_groups_sensors_and_altitude(tmp_path):
    with client(tmp_path) as c:
        from app.main import create_app  # noqa: F401  (the app is already started via the client)
        db = c.app.state.db
        tid = c.get("/api/trackers").json()[0]["id"]
        for ts, v, alt in [(1000, 4.1, 300.0), (2000, 4.0, 305.0), (3000, 3.9, None)]:
            db.add_sensors(tid, ts, [(2, "voltage", v), (3, "temperature", 20 + v)])
            if alt is not None:
                db.add_fix(tid, ts, 47.0, 8.0, alt, "telemetry")
        db.add_fix(tid, 4000, 47.0, 8.0, 999.0, "advert")   # an advert's altitude does not count

        data = {s["key"]: s["points"] for s in c.get(f"/api/trackers/{tid}/series").json()}
        assert data["voltage:2"] == [[1000, 4.1], [2000, 4.0], [3000, 3.9]]
        assert [p[0] for p in data["temperature:3"]] == [1000, 2000, 3000]
        assert data["gps_altitude:0"] == [[1000, 300.0], [2000, 305.0]]
        since = {s["key"]: s["points"] for s in c.get(f"/api/trackers/{tid}/series?since=2000").json()}
        assert since["voltage:2"] == [[2000, 4.0], [3000, 3.9]]
        assert c.get("/api/trackers/999/series").status_code == 404


def test_gpx_uses_telemetry_track_and_skips_adverts(tmp_path):
    with client(tmp_path) as c:
        db = c.app.state.db
        tid = c.get("/api/trackers").json()[0]["id"]
        db.add_fix(tid, 1000, 47.001, 8.001, None, "telemetry")
        db.add_fix(tid, 1100, 47.002, 8.002, None, "telemetry")
        db.add_fix(tid, 1200, 46.000, 7.000, None, "advert")        # stale advert place, newer time
        gpx = c.get(f"/api/trackers/{tid}/export.gpx").text
        assert gpx.count("<trkpt") == 2 and "46.000000" not in gpx


def test_tracker_view_shows_what_the_node_reports_from_the_last_advert(tmp_path):
    with client(tmp_path) as c:
        advert = c.get("/api/trackers").json()[0]["advert_now"]
        assert advert["lat"] is not None and abs(advert["lat"] - 47.3769) < 1e-4 and advert["ts"]
