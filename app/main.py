"""Web-API und Auslieferung der Karten-Oberfläche."""
from __future__ import annotations

import asyncio
import base64
import logging
import os
import re
import secrets
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from .config import Settings
from .db import Database
from .link import KEY_RE, Link, path_len
from .service import TrackerService

log = logging.getLogger("meshtracker")
STATIC_DIR = Path(__file__).parent / "static"


class TrackerIn(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    public_key: str
    interval_min: int = Field(default=10, ge=1, le=1440)
    route_mode: str = "auto"

    @field_validator("public_key")
    @classmethod
    def _key(cls, v: str) -> str:
        v = v.strip().lower()
        if not KEY_RE.match(v):
            raise ValueError("Public Key muss aus 64 Hex-Zeichen bestehen")
        return v

    @field_validator("route_mode")
    @classmethod
    def _mode(cls, v: str) -> str:
        if v not in ("auto", "flood"):
            raise ValueError("route_mode muss 'auto' oder 'flood' sein")
        return v

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Name darf nicht leer sein")
        return v


class TrackerPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=40)
    interval_min: int | None = Field(default=None, ge=1, le=1440)
    route_mode: str | None = None
    enabled: bool | None = None

    @field_validator("route_mode")
    @classmethod
    def _mode(cls, v: str | None) -> str | None:
        if v is not None and v not in ("auto", "flood"):
            raise ValueError("route_mode muss 'auto' oder 'flood' sein")
        return v


def _make_link(s: Settings) -> Link:
    if s.transport == "sim":
        from .sim import SimLink

        return SimLink(seed=1)
    if s.transport in ("tcp", "serial"):
        from .link import MeshCoreLink

        return MeshCoreLink(s)
    raise SystemExit(f"Unbekannter MT_TRANSPORT: {s.transport!r} (erlaubt: tcp, serial, sim)")


def create_app(settings: Settings | None = None, link: Link | None = None) -> FastAPI:
    s = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        Path(s.db_path).parent.mkdir(parents=True, exist_ok=True)
        db = Database(s.db_path)
        db.prune()
        lk = link or _make_link(s)
        svc = TrackerService(db, lk, s)
        app.state.db, app.state.link, app.state.svc = db, lk, svc
        if s.transport == "sim" and not db.list_trackers():
            from .sim import SIM_KEY

            db.add_tracker("Sim-Tracker", SIM_KEY, 1, "auto")
        tasks = [asyncio.create_task(lk.run(), name="link"),
                 asyncio.create_task(svc.run(), name="service")]
        try:
            yield
        finally:
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await lk.close()
            db.close()

    app = FastAPI(title="MeshTracker", lifespan=lifespan)

    if s.auth_user and s.auth_password:
        expected = base64.b64encode(f"{s.auth_user}:{s.auth_password}".encode()).decode()

        @app.middleware("http")
        async def basic_auth(request: Request, call_next):
            if request.url.path == "/healthz":
                return await call_next(request)
            header = request.headers.get("authorization", "")
            scheme, _, token = header.partition(" ")
            if scheme.lower() == "basic" and secrets.compare_digest(token.strip(), expected):
                return await call_next(request)
            return Response(status_code=401, headers={"WWW-Authenticate": 'Basic realm="MeshTracker"'})

    def db_() -> Database:
        return app.state.db

    def svc_() -> TrackerService:
        return app.state.svc

    def need(tracker_id: int) -> dict:
        tr = db_().get_tracker(tracker_id)
        if tr is None:
            raise HTTPException(404, "Tracker nicht gefunden")
        return tr

    def view(tr: dict) -> dict:
        db = db_()
        rt = svc_().runtime(tr["id"])
        contact = app.state.link.get_contact(tr["public_key"])
        plen = path_len(contact)
        polls = db.recent_polls(tr["id"], 1)
        return {
            **tr,
            "enabled": bool(tr["enabled"]),
            "fix": db.latest_fix(tr["id"]),
            "sensors": db.latest_sensors(tr["id"]),
            "last_poll": polls[0] if polls else None,
            "next_poll_ts": int(rt.next_due) if rt and rt.next_due else None,
            "polling": bool(rt and rt.polling),
            "known_on_node": contact is not None,
            "route_now": None if contact is None else ("flood" if plen < 0 else "path"),
            "hops_now": plen if plen >= 0 else None,
        }

    @app.get("/healthz")
    async def healthz():
        return {"ok": True}

    @app.get("/api/config")
    async def config():
        return {"tile_url": s.tile_url, "tile_attribution": s.tile_attribution,
                "tile_max_zoom": s.tile_max_zoom}

    @app.get("/api/status")
    async def status():
        lk = app.state.link
        return {"connected": bool(lk.connected), "error": lk.error, "now": int(time.time()),
                **lk.describe()}

    @app.get("/api/contacts")
    async def contacts():
        known = {t["public_key"] for t in db_().list_trackers()}
        out = [
            {"public_key": k, "name": c.get("adv_name") or k[:8], "type": c.get("type"),
             "path_len": path_len(c), "last_advert": c.get("last_advert"),
             "tracked": k in known}
            for k, c in app.state.link.contacts().items()
        ]
        return sorted(out, key=lambda c: c["name"].lower())

    @app.get("/api/trackers")
    async def list_trackers():
        return [view(t) for t in db_().list_trackers()]

    @app.post("/api/trackers", status_code=201)
    async def add_tracker(body: TrackerIn):
        if db_().get_tracker_by_key(body.public_key):
            raise HTTPException(409, "Dieser Tracker ist bereits angelegt")
        tr = db_().add_tracker(body.name, body.public_key, body.interval_min, body.route_mode)
        svc_().request_poll(tr["id"])
        return view(tr)

    @app.patch("/api/trackers/{tracker_id}")
    async def patch_tracker(tracker_id: int, body: TrackerPatch):
        need(tracker_id)
        data = body.model_dump(exclude_none=True)
        if "enabled" in data:
            data["enabled"] = int(data["enabled"])
        tr = db_().update_tracker(tracker_id, **data)
        if "interval_min" in data:
            svc_().reschedule(tracker_id)
        return view(tr)  # type: ignore[arg-type]

    @app.delete("/api/trackers/{tracker_id}", status_code=204)
    async def delete_tracker(tracker_id: int):
        need(tracker_id)
        db_().delete_tracker(tracker_id)
        return Response(status_code=204)

    @app.post("/api/trackers/{tracker_id}/poll", status_code=202)
    async def poll_now(tracker_id: int):
        need(tracker_id)
        svc_().request_poll(tracker_id)
        return {"queued": True}

    @app.post("/api/trackers/{tracker_id}/reset-path")
    async def reset_path(tracker_id: int):
        tr = need(tracker_id)
        ok, why = await svc_().reset_path_manual(tr)
        if not ok:
            return JSONResponse({"ok": False, "error": why}, status_code=502)
        return {"ok": True}

    @app.get("/api/trackers/{tracker_id}/track")
    async def track(tracker_id: int, since: int = Query(0, ge=0), limit: int = Query(5000, ge=1, le=20000)):
        need(tracker_id)
        return db_().fixes(tracker_id, since, limit)

    @app.get("/api/trackers/{tracker_id}/series")
    async def series(tracker_id: int, since: int = Query(0, ge=0)):
        need(tracker_id)
        return db_().series(tracker_id, since)

    @app.get("/api/trackers/{tracker_id}/polls")
    async def polls(tracker_id: int, limit: int = Query(20, ge=1, le=200)):
        need(tracker_id)
        return db_().recent_polls(tracker_id, limit)

    @app.get("/api/trackers/{tracker_id}/export.gpx")
    async def export_gpx(tracker_id: int, since: int = Query(0, ge=0)):
        tr = need(tracker_id)
        pts = []
        for f in db_().fixes(tracker_id, since, 20000):
            t = datetime.fromtimestamp(f["ts"], timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            ele = f"<ele>{f['alt']}</ele>" if f["alt"] is not None else ""
            pts.append(f'<trkpt lat="{f["lat"]:.6f}" lon="{f["lon"]:.6f}">{ele}<time>{t}</time></trkpt>')
        name = escape(tr["name"])
        body = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<gpx version="1.1" creator="MeshTracker" xmlns="http://www.topografix.com/GPX/1/1">'
            f"<trk><name>{name}</name><trkseg>{''.join(pts)}</trkseg></trk></gpx>"
        )
        fname = re.sub(r"[^A-Za-z0-9_.-]+", "_", tr["name"]) or "tracker"
        return Response(body, media_type="application/gpx+xml",
                        headers={"Content-Disposition": f'attachment; filename="{fname}.gpx"'})

    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
    return app


def app_factory() -> FastAPI:
    logging.basicConfig(level=os.environ.get("MT_LOG_LEVEL", "INFO"),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    return create_app()
