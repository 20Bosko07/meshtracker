import asyncio
import dataclasses

import pytest

from app.config import Settings
from app.db import Database
from app.service import TrackerService
from app.sim import SIM_KEY, SimLink


class Clock:
    def __init__(self, t=1_800_000_000.0):
        self.t = t

    def __call__(self):
        return self.t

    async def sleep(self, seconds):
        self.t += seconds


def make(tmp_path, link=None, mode="auto", **settings):
    s = dataclasses.replace(Settings(), min_spacing=0, flood_backoff=0, db_path=str(tmp_path / "t.db"), **settings)
    db = Database(s.db_path)
    link = link or SimLink(seed=1)
    clock = Clock()
    svc = TrackerService(db, link, s, clock=clock, sleep=clock.sleep)
    tr = db.add_tracker("T", SIM_KEY, 10, mode)
    return db, link, svc, tr, clock


def run(coro):
    return asyncio.run(coro)


def test_path_works_first_try(tmp_path):
    db, link, svc, tr, _ = make(tmp_path, SimLink(path_breaks_after=99))
    res = run(svc.poll_once(tr))
    assert res.ok and res.has_gps and res.route == "path"
    assert link.calls == ["path"] and link.resets == 0
    fix = db.latest_fix(tr["id"])
    assert fix["source"] == "telemetry" and fix["route"] == "path" and fix["hops"] == 2
    assert {s["type"] for s in db.latest_sensors(tr["id"])} == {"voltage", "temperature"}


def test_dead_path_falls_back_to_flood_immediately(tmp_path):
    link = SimLink(path_breaks_after=1, flood_loss=0.0)
    link._path_ok_count = 1  # the path is already stale
    db, link, svc, tr, _ = make(tmp_path, link)
    res = run(svc.poll_once(tr))
    assert res.ok and res.route == "flood"
    assert link.calls == ["path", "flood"]  # no second path attempt
    assert link.resets == 1
    assert db.latest_fix(tr["id"])["route"] == "flood"
    # the flood reply taught the node a new path → the next poll goes by path
    res2 = run(svc.poll_once(tr))
    assert res2.route == "path" and link.calls[-1] == "path"


def test_flood_is_retried_then_gives_up(tmp_path):
    db, link, svc, tr, _ = make(tmp_path, SimLink(path_breaks_after=0, flood_loss=1.0), flood_retries=2)
    res = run(svc.poll_once(tr))
    assert not res.ok
    assert link.calls == ["path", "flood", "flood"]
    assert "3 attempts" in res.error
    assert db.latest_fix(tr["id"]) is None
    assert db.recent_polls(tr["id"])[0]["ok"] == 0


def test_flood_mode_resets_path_before_request(tmp_path):
    db, link, svc, tr, _ = make(tmp_path, SimLink(path_breaks_after=99, flood_loss=0.0), mode="flood")
    res = run(svc.poll_once(tr))
    assert res.ok and res.route == "flood"
    assert link.calls == ["flood"] and link.resets == 1


def test_reset_rejected_by_device_is_reported(tmp_path):
    link = SimLink(path_breaks_after=0, accept_reset=False)
    db, link, svc, tr, _ = make(tmp_path, link)
    res = run(svc.poll_once(tr))
    assert not res.ok
    assert link.calls == ["path", "path", "path"]
    assert "Path reset failed" in res.error


def test_response_without_gps_is_flagged(tmp_path):
    link = SimLink(path_breaks_after=99)
    link.has_gps = False
    db, link, svc, tr, _ = make(tmp_path, link)
    res = run(svc.poll_once(tr))
    assert res.ok and not res.has_gps and "without GPS" in res.error
    assert db.latest_fix(tr["id"]) is None
    assert db.latest_sensors(tr["id"])  # Sensorwerte werden trotzdem gespeichert


def test_unknown_contact_and_disconnected(tmp_path):
    db, link, svc, tr, _ = make(tmp_path)
    other = db.add_tracker("X", "cd" * 32, 10, "auto")
    res = run(svc.poll_once(other))
    assert not res.ok and "contact list" in res.error
    link.connected = False
    res = run(svc.poll_once(tr))
    assert not res.ok and "No connection" in res.error


def test_advert_position_is_recorded_once(tmp_path):
    db, link, svc, tr, clock = make(tmp_path)
    link._contacts[SIM_KEY]["last_advert"] = int(clock())
    run(svc.on_advert(SIM_KEY))
    run(svc.on_advert(SIM_KEY))
    fixes = db.fixes(tr["id"])
    assert len(fixes) == 1 and fixes[0]["source"] == "advert"


def test_tick_schedules_by_interval_and_retries_failures_sooner(tmp_path):
    db, link, svc, tr, clock = make(tmp_path, SimLink(path_breaks_after=99), fail_retry=180)
    run(svc.tick())                      # sets up the schedule, nothing due yet
    assert db.recent_polls(tr["id"]) == []
    clock.t += 5
    run(svc.tick())
    assert len(db.recent_polls(tr["id"])) == 1
    assert svc.runtime(tr["id"]).next_due == pytest.approx(clock.t + 600)

    link.connected = False               # failure → retry sooner
    svc.request_poll(tr["id"])
    run(svc.tick())
    assert svc.runtime(tr["id"]).next_due == pytest.approx(clock.t + 180)


def test_manual_request_poll_runs_next_tick(tmp_path):
    db, link, svc, tr, clock = make(tmp_path, SimLink(path_breaks_after=99))
    run(svc.tick())
    svc.request_poll(tr["id"])
    run(svc.tick())
    assert len(db.recent_polls(tr["id"])) == 1


def test_refused_by_device_stops_after_first_attempt(tmp_path):
    db, link, svc, tr, _ = make(tmp_path, SimLink(refuse=True))
    res = run(svc.poll_once(tr))
    assert not res.ok and link.calls == ["refused"] and link.resets == 0
    assert "refused" in res.error


def test_stale_contact_view_still_recovers_by_resetting(tmp_path):
    """The Virtual Node shows "flood" but the node holds a dead path:
    without a reset every attempt would run into the void."""
    link = SimLink(path_breaks_after=99, flood_loss=0.0, real_path_dead=True)
    link._contacts[SIM_KEY]["out_path_len"] = -1
    db, link, svc, tr, _ = make(tmp_path, link)
    res = run(svc.poll_once(tr))
    assert res.ok and link.resets == 1 and link.calls == ["flood", "flood"]


def test_flood_mode_resets_even_if_view_says_flood(tmp_path):
    link = SimLink(path_breaks_after=99, flood_loss=0.0, real_path_dead=True)
    link._contacts[SIM_KEY]["out_path_len"] = -1
    db, link, svc, tr, _ = make(tmp_path, link, mode="flood")
    res = run(svc.poll_once(tr))
    assert res.ok and link.resets == 1 and link.calls == ["flood"]


def test_failed_round_leaves_path_reset_for_next_poll(tmp_path):
    db, link, svc, tr, _ = make(tmp_path, SimLink(path_breaks_after=0, flood_loss=1.0), flood_retries=1)
    run(svc.poll_once(tr))
    assert link.get_contact(SIM_KEY)["out_path_len"] == -1 and link.resets == 2


def test_latest_position_prefers_gps_telemetry_over_a_newer_advert(tmp_path):
    db, link, svc, tr, _ = make(tmp_path)
    assert db.latest_fix(tr["id"]) is None
    db.add_fix(tr["id"], 5000, 47.1, 8.1, None, "advert")
    assert db.latest_fix(tr["id"])["source"] == "advert"        # fallback while nothing else exists
    db.add_fix(tr["id"], 1000, 47.5, 8.5, 400.0, "telemetry")   # older timestamp, but real GPS
    assert db.latest_fix(tr["id"])["source"] == "telemetry"
    assert db.latest_fix(tr["id"])["lat"] == 47.5


def test_advert_position_is_stored_only_when_it_changes(tmp_path):
    """Via a Virtual Node the contact's 'last advert' time keeps moving while the
    coordinates stay the old advert location – that must not pile up points."""
    db, link, svc, tr, clock = make(tmp_path)
    contact = link._contacts[SIM_KEY]
    for step in range(4):
        contact["last_advert"] = int(clock()) - 600 + step * 120   # time moves, place does not
        run(svc.on_advert(SIM_KEY))
    assert len(db.fixes(tr["id"])) == 1
    contact["adv_lat"], contact["adv_lon"] = 47.40, 8.60            # the advert really moved
    contact["last_advert"] = int(clock())
    run(svc.on_advert(SIM_KEY))
    assert [round(f["lat"], 2) for f in db.fixes(tr["id"])] == [47.38, 47.40]


def test_advert_timestamp_is_never_in_the_future(tmp_path):
    db, link, svc, tr, clock = make(tmp_path)
    link._contacts[SIM_KEY]["last_advert"] = int(clock()) + 3600    # tracker clock one hour ahead
    run(svc.on_advert(SIM_KEY))
    assert db.fixes(tr["id"])[0]["ts"] <= int(clock())


def test_advert_sync_runs_at_the_configured_interval(tmp_path):
    db, link, svc, tr, clock = make(tmp_path, SimLink(path_breaks_after=99), advert_sync=60)
    db.update_tracker(tr["id"], enabled=0)               # no polling in this test
    adverts = lambda: len([f for f in db.fixes(tr["id"]) if f["source"] == "advert"])  # noqa: E731
    run(svc.tick())                                      # the first tick syncs right away
    assert adverts() == 1
    link._contacts[SIM_KEY]["adv_lat"] = 47.41           # the tracker advertised a new place
    clock.t += 30
    run(svc.tick())
    assert adverts() == 1                                # not due yet
    clock.t += 40
    run(svc.tick())
    assert adverts() == 2                                # 70 s later it is picked up
