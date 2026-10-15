"""Ende-zu-Ende gegen einen Fake-Companion mit der echten meshcore-Bibliothek."""
import asyncio
import dataclasses

from app.config import Settings
from app.db import Database
from app.link import MeshCoreLink
from app.service import TrackerService

from .fake_companion import TRACKER_KEY, FakeCompanion

KEY = TRACKER_KEY.hex()


async def scenario(tmp_path, configure, body):
    node = FakeCompanion()
    configure(node)
    port = await node.start()
    s = dataclasses.replace(Settings(), transport="tcp", host="127.0.0.1", port=port,
                            db_path=str(tmp_path / "e2e.db"), min_spacing=0, flood_backoff=0,
                            path_timeout_floor=0.3, flood_timeout_floor=0.3)
    db = Database(s.db_path)
    link = MeshCoreLink(s)
    svc = TrackerService(db, link, s)
    task = asyncio.create_task(link.run())
    try:
        for _ in range(100):
            if link.connected and link.get_contact(KEY):
                break
            await asyncio.sleep(0.1)
        assert link.connected, link.error
        tr = db.add_tracker("T", KEY, 10, "auto")
        await body(node, link, svc, db, tr)
    finally:
        task.cancel()
        await link.close()
        await node.stop()
        db.close()


def run(tmp_path, configure, body):
    asyncio.run(asyncio.wait_for(scenario(tmp_path, configure, body), 30))


def test_connects_and_reads_contacts(tmp_path):
    async def body(node, link, svc, db, tr):
        c = link.get_contact(KEY)
        assert c["adv_name"] == "Tracker-1" and c["out_path_len"] == 2
        assert link.describe()["node_name"] == "FakeNode"
    run(tmp_path, lambda n: None, body)


def test_telemetry_over_working_path(tmp_path):
    async def body(node, link, svc, db, tr):
        res = await svc.poll_once(tr)
        assert res.ok and res.has_gps and res.route == "path"
        assert node.requests == ["path"]
        fix = db.latest_fix(tr["id"])
        assert abs(fix["lat"] - 47.3769) < 1e-4 and fix["alt"] == 410.0 and fix["hops"] == 2
        assert {s["type"] for s in db.latest_sensors(tr["id"])} == {"voltage", "temperature"}
    run(tmp_path, lambda n: None, body)


def test_dead_path_switches_to_flood_and_node_relearns_path(tmp_path):
    async def body(node, link, svc, db, tr):
        res = await svc.poll_once(tr)
        assert res.ok and res.route == "flood", res.error
        assert node.requests == ["path", "flood"] and node.resets == 1
        assert db.latest_fix(tr["id"])["route"] == "flood"
        node.path_dead = False          # Pfad wurde neu gelernt → wieder normal
        await link.refresh_contacts()
        res2 = await svc.poll_once(tr)
        assert res2.route == "path"
    run(tmp_path, lambda n: setattr(n, "path_dead", True), body)


def test_flood_mode_always_resets_first(tmp_path):
    async def body(node, link, svc, db, tr):
        db.update_tracker(tr["id"], route_mode="flood")
        res = await svc.poll_once(db.get_tracker(tr["id"]))
        assert res.ok and res.route == "flood"
        assert node.requests == ["flood"] and node.resets == 1
    run(tmp_path, lambda n: None, body)


def test_device_refusing_reset_is_reported(tmp_path):
    async def body(node, link, svc, db, tr):
        res = await svc.poll_once(tr)
        assert not res.ok
        assert "Pfad-Reset fehlgeschlagen" in res.error
        # lokaler Cache wurde mit dem Gerät abgeglichen (Pfad existiert weiter)
        assert link.get_contact(KEY)["out_path_len"] == 2
    run(tmp_path, lambda n: (setattr(n, "path_dead", True), setattr(n, "accept_reset", False)), body)


def test_advert_push_records_position(tmp_path):
    async def body(node, link, svc, db, tr):
        node.lat, node.lon = 47.4, 8.6
        await node.push_advert()
        for _ in range(50):
            fix = db.latest_fix(tr["id"])
            if fix:
                break
            await asyncio.sleep(0.1)
        assert fix and fix["source"] == "advert" and abs(fix["lat"] - 47.4) < 1e-4
    run(tmp_path, lambda n: None, body)
