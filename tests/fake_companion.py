"""Minimaler Fake eines MeshCore-Companions (TCP-Framing + die paar Befehle,
die MeshTracker nutzt). Damit lässt sich die echte ``meshcore``-Bibliothek
und MeshCoreLink ohne Funkhardware Ende-zu-Ende testen."""
from __future__ import annotations

import asyncio
import os
import struct
import time

from cayennelpp import LppFrame

TRACKER_KEY = bytes.fromhex("ab" * 32)

CMD_APPSTART, CMD_GET_CONTACTS, CMD_RESET_PATH, CMD_BINARY_REQ = 1, 4, 13, 50
PKT_OK, PKT_ERROR, PKT_CONTACT_START, PKT_CONTACT, PKT_CONTACT_END = 0, 1, 2, 3, 4
PKT_SELF_INFO, PKT_MSG_SENT, PKT_ADVERT, PKT_BINARY_RESPONSE = 5, 6, 0x80, 0x8C


def frame(data: bytes) -> bytes:
    return b"\x3e" + struct.pack("<H", len(data)) + data


class FakeCompanion:
    def __init__(self):
        self.path_len = 2            # -1 = Flood
        self.path_dead = False       # Pfad antwortet nicht mehr
        self.flood_ok = True
        self.accept_reset = True
        self.suggested_timeout = 240  # ms*… → Bibliothek teilt durch 800 → 0,3 s
        self.lat, self.lon = 47.3769, 8.5417
        self.requests: list[str] = []  # "path"/"flood" je Telemetrie-Anfrage
        self.resets = 0
        self._writers: list[asyncio.StreamWriter] = []
        self.server: asyncio.base_events.Server | None = None

    async def start(self) -> int:
        self.server = await asyncio.start_server(self._client, "127.0.0.1", 0)
        return self.server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        for w in self._writers:
            w.close()
        if self.server:
            self.server.close()
            await self.server.wait_closed()

    # --- Frames ------------------------------------------------------------

    def _self_info(self) -> bytes:
        return (bytes([PKT_SELF_INFO, 1, 20, 22]) + os.urandom(32) + struct.pack("<ii", 0, 0)
                + bytes([0, 0, 0, 0]) + struct.pack("<II", 869525, 250000) + bytes([11, 5]) + b"FakeNode")

    def _contact(self) -> bytes:
        plen = 255 if self.path_len < 0 else self.path_len
        path = (b"\xa1\xb2\xc3"[: max(self.path_len, 0)]).ljust(64, b"\0")
        name = b"Tracker-1".ljust(32, b"\0")
        return (bytes([PKT_CONTACT]) + TRACKER_KEY + bytes([4, 0, plen]) + path + name
                + struct.pack("<Iii", int(time.time()), int(self.lat * 1e6), int(self.lon * 1e6))
                + struct.pack("<I", int(time.time())))

    def _lpp(self) -> bytes:
        f = LppFrame()
        f.add_gps(1, self.lat, self.lon, 410.0)
        f.add_voltage(2, 3.95)
        f.add_temperature(3, 18.5)
        return bytes(f)

    async def push_advert(self) -> None:
        for w in self._writers:
            w.write(frame(bytes([PKT_ADVERT]) + TRACKER_KEY))
            await w.drain()

    # --- Verbindung ---------------------------------------------------------

    async def _client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self._writers.append(writer)
        try:
            while True:
                head = await reader.readexactly(3)
                size = struct.unpack("<H", head[1:])[0]
                cmd = await reader.readexactly(size)
                for out in self._handle(cmd):
                    writer.write(frame(out))
                await writer.drain()
                if cmd[0] == CMD_BINARY_REQ:
                    await self._maybe_respond(writer, cmd)
        except (asyncio.IncompleteReadError, ConnectionError):
            pass

    def _handle(self, cmd: bytes) -> list[bytes]:
        code = cmd[0]
        if code == CMD_APPSTART:
            return [self._self_info()]
        if code == CMD_GET_CONTACTS:
            return [bytes([PKT_CONTACT_START]) + struct.pack("<I", 1), self._contact(),
                    bytes([PKT_CONTACT_END]) + struct.pack("<I", int(time.time()))]
        if code == CMD_RESET_PATH:
            if not self.accept_reset:
                return [bytes([PKT_ERROR, 1])]
            self.resets += 1
            self.path_len = -1
            return [bytes([PKT_OK])]
        if code == CMD_BINARY_REQ:
            self.requests.append("flood" if self.path_len < 0 else "path")
            return [bytes([PKT_MSG_SENT, 0]) + b"\x01\x02\x03\x04" + struct.pack("<I", self.suggested_timeout)]
        return [bytes([PKT_ERROR, 1])]

    async def _maybe_respond(self, writer: asyncio.StreamWriter, cmd: bytes) -> None:
        via_path = self.requests[-1] == "path"
        if via_path and self.path_dead:
            return
        if not via_path and not self.flood_ok:
            return
        if not via_path:
            self.path_len = 2  # Antwort per Flood → Node lernt neuen Pfad
        await asyncio.sleep(0.02)
        writer.write(frame(bytes([PKT_BINARY_RESPONSE, 0]) + b"\x01\x02\x03\x04" + self._lpp()))
        await writer.drain()
