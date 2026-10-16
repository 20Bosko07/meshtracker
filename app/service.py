"""Scheduling and polling logic: one telemetry request per tracker at a regular
interval, with an automatic switch from the stored path to flood when the path
no longer works."""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from .config import Settings
from .db import Database
from .link import Link, path_len
from .lpp import extract

log = logging.getLogger("meshtracker.service")

ADVERT_SYNC_S = 300.0
SANE_CLOCK_S = 2 * 86400


@dataclass
class Runtime:
    next_due: float
    polling: bool = False
    last_end: float | None = None


@dataclass
class PollResult:
    ok: bool
    has_gps: bool = False
    route: str | None = None
    attempts: list[str] = field(default_factory=list)
    duration_ms: int = 0
    error: str | None = None


def _valid_pos(lat: float | None, lon: float | None) -> bool:
    if lat is None or lon is None:
        return False
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return False
    return not (abs(lat) < 1e-6 and abs(lon) < 1e-6)


class TrackerService:
    def __init__(
        self,
        db: Database,
        link: Link,
        settings: Settings,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ):
        self.db = db
        self.link = link
        self.s = settings
        self._clock = clock
        self._sleep = sleep
        self._rt: dict[int, Runtime] = {}
        self._mesh_lock = asyncio.Lock()
        self._last_mesh_end = 0.0
        self._last_advert_sync = 0.0
        link.set_advert_callback(self.on_advert)

    # --- State for the API -------------------------------------------------

    def runtime(self, tracker_id: int) -> Runtime | None:
        return self._rt.get(tracker_id)

    def request_poll(self, tracker_id: int) -> bool:
        """Queue an immediate poll (run by the scheduler loop)."""
        rt = self._rt.get(tracker_id)
        if rt is None:
            rt = self._rt[tracker_id] = Runtime(next_due=0.0)
        rt.next_due = 0.0
        return True

    def reschedule(self, tracker_id: int) -> None:
        """After the interval changed: recompute the next poll."""
        tr = self.db.get_tracker(tracker_id)
        rt = self._rt.get(tracker_id)
        if tr is None or rt is None:
            return
        base = rt.last_end if rt.last_end is not None else self._clock()
        rt.next_due = min(rt.next_due, base + tr["interval_min"] * 60)

    # --- Polling one tracker ---------------------------------------------

    async def poll_once(self, tr: dict) -> PollResult:
        async with self._mesh_lock:
            return await self._poll_once(tr)

    async def _poll_once(self, tr: dict) -> PollResult:
        t0 = self._clock()
        key = tr["public_key"]
        attempts: list[str] = []
        notes: list[str] = []

        def finish(result: PollResult) -> PollResult:
            result.attempts = attempts
            result.duration_ms = int((self._clock() - t0) * 1000)
            self.db.add_poll(
                tr["id"], int(t0), result.ok, result.has_gps, result.route,
                ",".join(attempts), result.duration_ms, result.error,
            )
            return result

        if not self.link.connected:
            return finish(PollResult(False, error="No connection to the MeshCore node"))

        # Refresh the contact list: behind MeshMonitor's Virtual Node the tracker's
        # path changes without us receiving a push.
        try:
            await self.link.refresh_contacts()
        except Exception as exc:
            log.warning("Could not refresh the contact list: %s", exc)
        contact = self.link.get_contact(key)
        if contact is None:
            return finish(PollResult(
                False,
                error="Tracker is not in the node's contact list – wait for its advert "
                      "or add the contact on the node",
            ))

        # "Always flood" mode: drop the stored path before every poll – regardless of
        # what our contact copy shows (it may be stale).
        if tr["route_mode"] == "flood":
            ok, why = await self.link.reset_path(key)
            if not ok:
                notes.append(f"Path reset failed: {why}")
            contact = self.link.get_contact(key) or contact

        max_attempts = 1 + max(0, self.s.flood_retries)
        lpp = None
        route = "flood"
        last_reason = ""
        for n in range(max_attempts):
            contact = self.link.get_contact(key) or contact
            route = "flood" if path_len(contact) < 0 else "path"
            floor = self.s.flood_timeout_floor if route == "flood" else self.s.path_timeout_floor
            attempts.append(route)
            reply = await self.link.request_telemetry(key, floor)
            lpp = reply.lpp
            if lpp is not None:
                break
            last_reason = reply.error or ""
            if reply.refused:
                break  # Device refuses – retrying or resetting the path will not help
            # No reply → the path on the node may be dead even if our contact copy
            # says "flood". Always reset: the next attempt (and the next scheduled
            # poll) then definitely goes by flood.
            ok, why = await self.link.reset_path(key)
            if not ok:
                notes.append(f"Path reset failed: {why}")
            if route == "flood" and n < max_attempts - 1:
                await self._sleep(self.s.flood_backoff)

        if lpp is None:
            if last_reason.startswith("Request refused"):
                msg = last_reason
            else:
                msg = f"No reply after {len(attempts)} attempts ({' → '.join(attempts)})"
                if last_reason:
                    msg += f": {last_reason}"
            if notes:
                msg += "; " + "; ".join(dict.fromkeys(notes))
            return finish(PollResult(False, error=msg))

        now = int(self._clock())
        fix, readings = extract(lpp)
        hops = None
        if route == "path":
            hops = path_len(self.link.get_contact(key))
            hops = hops if hops >= 0 else None
        if readings:
            self.db.add_sensors(tr["id"], now, [(r.channel, r.type, r.value) for r in readings])
        if fix is not None:
            self.db.add_fix(tr["id"], now, fix.lat, fix.lon, fix.alt, "telemetry", route, hops)
            error = "; ".join(dict.fromkeys(notes)) or None
            return finish(PollResult(True, True, route, error=error))
        error = "Reply without GPS position (no GPS fix, or location telemetry not allowed)"
        return finish(PollResult(True, False, route, error=error))

    async def reset_path_manual(self, tr: dict) -> tuple[bool, str]:
        async with self._mesh_lock:
            return await self.link.reset_path(tr["public_key"])

    # --- Adverts -------------------------------------------------------------

    async def on_advert(self, key: str) -> None:
        tr = self.db.get_tracker_by_key(key)
        if tr is not None:
            self._record_advert(tr)

    def _record_advert(self, tr: dict) -> None:
        contact = self.link.get_contact(tr["public_key"])
        if not contact:
            return
        lat, lon = contact.get("adv_lat"), contact.get("adv_lon")
        if not _valid_pos(lat, lon):
            return
        # Store an advert position only when the coordinates actually changed. Behind
        # MeshMonitor's Virtual Node the contact's "last advert" time moves whenever the
        # tracker is heard at all, while the coordinates stay the old advert location –
        # storing it every time would pile up stale points with fresh timestamps.
        last = self.db.latest_advert_fix(tr["id"])
        if last and abs(last["lat"] - lat) < 1e-6 and abs(last["lon"] - lon) < 1e-6:
            return
        now = int(self._clock())
        stamp = int(contact.get("last_advert") or 0)
        # Never later than now; an unset tracker clock falls back to our own time.
        ts = min(stamp, now) if abs(stamp - now) < SANE_CLOCK_S else now
        self.db.add_fix(tr["id"], ts, lat, lon, None, "advert")

    def sync_adverts(self) -> None:
        for tr in self.db.list_trackers():
            self._record_advert(tr)

    # --- Scheduler ------------------------------------------------------------

    async def run(self) -> None:
        while True:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Error in the scheduler loop")
            await self._sleep(2)

    async def tick(self) -> None:
        now = self._clock()
        trackers = self.db.list_trackers()
        live = {t["id"] for t in trackers}
        for gone in set(self._rt) - live:
            del self._rt[gone]
        for idx, tr in enumerate(trackers):
            self._rt.setdefault(tr["id"], Runtime(next_due=now + 3 + 20 * idx))

        if now - self._last_advert_sync >= ADVERT_SYNC_S:
            self._last_advert_sync = now
            if self.link.connected:
                self.sync_adverts()

        due = [t for t in trackers if t["enabled"] and self._rt[t["id"]].next_due <= now]
        if not due:
            return
        tr = min(due, key=lambda t: self._rt[t["id"]].next_due)
        rt = self._rt[tr["id"]]

        wait = self.s.min_spacing - (self._clock() - self._last_mesh_end)
        if wait > 0:
            await self._sleep(wait)

        rt.polling = True
        try:
            result = await self.poll_once(tr)
        finally:
            rt.polling = False
        end = self._clock()
        self._last_mesh_end = end
        rt.last_end = end
        interval = tr["interval_min"] * 60
        rt.next_due = end + (interval if result.ok else min(interval, self.s.fail_retry))
        log.info("Tracker %s: %s via %s (%s)", tr["name"], "ok" if result.ok else "FAILED",
                 "→".join(result.attempts) or "-", result.error or "")
