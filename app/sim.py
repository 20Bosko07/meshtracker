"""Simulator for demo and tests (``MT_TRANSPORT=sim``): a tracker circling around
Zurich whose path "breaks" regularly – so the path → flood switch can be watched
without radio hardware."""
from __future__ import annotations

import asyncio
import math
import random
import time

from .link import AdvertCallback, TelemetryReply, path_len

SIM_KEY = "ab" * 32
CENTER = (47.3769, 8.5417)


class SimLink:
    def __init__(self, *, path_breaks_after: int = 3, flood_loss: float = 0.25,
                 accept_reset: bool = True, refuse: bool = False,
                 real_path_dead: bool = False, seed: int | None = None, delay: float = 0.0):
        self.connected = True
        self.error = ""
        self.path_breaks_after = path_breaks_after
        self.flood_loss = flood_loss
        self.accept_reset = accept_reset
        self.refuse = refuse
        # The node holds a dead path but the contact list shows "flood" (stale view).
        self.real_path_dead = real_path_dead
        self.delay = delay
        self.has_gps = True
        self.calls: list[str] = []  # "path" / "flood" per request (for tests)
        self.resets = 0
        self._rng = random.Random(seed)
        self._path_ok_count = 0
        self._cb: AdvertCallback | None = None
        self._contacts = {
            SIM_KEY: {
                "public_key": SIM_KEY, "adv_name": "Sim-Tracker", "type": 4,
                "out_path_len": 2, "out_path": "a1b2", "last_advert": int(time.time()),
                "adv_lat": CENTER[0], "adv_lon": CENTER[1],
            }
        }

    def describe(self) -> dict:
        return {"transport": "sim", "target": "Simulator", "node_name": "Sim-Node"}

    def contacts(self) -> dict[str, dict]:
        return {k: dict(v) for k, v in self._contacts.items()}

    def get_contact(self, key: str) -> dict | None:
        c = self._contacts.get(key.lower())
        return dict(c) if c else None

    def set_advert_callback(self, cb: AdvertCallback) -> None:
        self._cb = cb

    async def refresh_contacts(self) -> None:
        return None

    def _position(self) -> tuple[float, float]:
        angle = (time.time() / 120.0) % (2 * math.pi)
        return CENTER[0] + 0.01 * math.sin(angle), CENTER[1] + 0.015 * math.cos(angle)

    async def request_telemetry(self, key: str, min_timeout: float) -> TelemetryReply:
        c = self._contacts.get(key.lower())
        if c is None:
            return TelemetryReply(None, "unknown contact", refused=True)
        if self.refuse:
            self.calls.append("refused")
            return TelemetryReply(None, "Request refused (ERR_CODE_BAD_STATE)", refused=True)
        if self.delay:
            await asyncio.sleep(self.delay)
        route = "flood" if path_len(c) < 0 else "path"
        self.calls.append(route)
        if self.real_path_dead:
            return TelemetryReply(None, "no reply within 48 s")
        if route == "path":
            if self._path_ok_count >= self.path_breaks_after:
                return TelemetryReply(None, "no reply within 10 s")  # stale path
            self._path_ok_count += 1
        else:
            if self._rng.random() < self.flood_loss:
                return TelemetryReply(None, "no reply within 25 s")
            # Reply by flood → node learns a new path
            c["out_path_len"] = self._rng.randint(1, 3)
            c["out_path"] = "c3d4"
            self._path_ok_count = 0
        lat, lon = self._position()
        lpp: list[dict] = [
            {"channel": 2, "type": "voltage", "value": round(3.9 + self._rng.random() * 0.2, 2)},
            {"channel": 3, "type": "temperature", "value": round(14 + self._rng.random() * 4, 1)},
        ]
        if self.has_gps:
            lpp.insert(0, {"channel": 1, "type": "gps",
                           "value": {"latitude": round(lat, 6), "longitude": round(lon, 6),
                                     "altitude": 410.0}})
        return TelemetryReply(lpp)

    async def reset_path(self, key: str) -> tuple[bool, str]:
        c = self._contacts.get(key.lower())
        if c is None:
            return False, "unknown contact"
        if not self.accept_reset:
            return False, "Device refuses path reset (UnsupportedCmd)"
        self.resets += 1
        self.real_path_dead = False
        c["out_path_len"] = -1
        c["out_path"] = ""
        return True, ""

    async def run(self) -> None:
        while True:
            await asyncio.sleep(3600)

    async def close(self) -> None:
        return None
