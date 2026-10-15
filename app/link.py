"""Verbindung zu einem MeshCore-Companion (USB, WiFi/TCP oder MeshMonitor
Virtual Node) auf Basis der ``meshcore``-Bibliothek."""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Awaitable, Callable, Protocol

from .config import Settings

log = logging.getLogger("meshtracker.link")

KEY_RE = re.compile(r"^[0-9a-f]{64}$")

AdvertCallback = Callable[[str], Awaitable[None]]


def path_len(contact: dict | None) -> int:
    """-1 = Flood (kein Pfad bekannt), 0 = direkt, n = n Hops."""
    if not contact:
        return -1
    try:
        return int(contact.get("out_path_len", -1))
    except (TypeError, ValueError):
        return -1


class Link(Protocol):
    """Was der Tracker-Dienst vom Funkgerät braucht."""

    connected: bool
    error: str

    def describe(self) -> dict: ...
    def contacts(self) -> dict[str, dict]: ...
    def get_contact(self, key: str) -> dict | None: ...
    async def refresh_contacts(self) -> None: ...
    async def request_telemetry(self, key: str, min_timeout: float) -> list[dict] | None: ...
    async def reset_path(self, key: str) -> tuple[bool, str]: ...
    def set_advert_callback(self, cb: AdvertCallback) -> None: ...
    async def run(self) -> None: ...
    async def close(self) -> None: ...


class MeshCoreLink:
    """Hält die Verbindung am Leben (Wiederverbindung mit Backoff)."""

    def __init__(self, settings: Settings):
        self.s = settings
        self.connected = False
        self.error = ""
        self._mc = None
        self._advert_cb: AdvertCallback | None = None
        self._stopping = False

    # --- Zustand -----------------------------------------------------------

    def describe(self) -> dict:
        if self.s.transport == "serial":
            target = f"{self.s.serial_port} @ {self.s.serial_baud}"
        else:
            target = f"{self.s.host}:{self.s.port}"
        info = (self._mc.self_info if self._mc is not None else None) or {}
        return {
            "transport": self.s.transport,
            "target": target,
            "node_name": info.get("name"),
        }

    def contacts(self) -> dict[str, dict]:
        return dict(self._mc.contacts) if self._mc is not None else {}

    def get_contact(self, key: str) -> dict | None:
        return self.contacts().get(key.lower())

    def set_advert_callback(self, cb: AdvertCallback) -> None:
        self._advert_cb = cb

    # --- Verbindung --------------------------------------------------------

    async def run(self) -> None:
        backoff = 5.0
        while not self._stopping:
            if self._mc is None or not self._mc.is_connected:
                self.connected = False
                if await self._connect():
                    backoff = 5.0
                else:
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 60.0)
                    continue
            self.connected = bool(self._mc and self._mc.is_connected)
            await asyncio.sleep(3)

    async def _connect(self) -> bool:
        from meshcore import EventType, MeshCore

        await self._drop()
        try:
            if self.s.transport == "serial":
                mc = await MeshCore.create_serial(
                    self.s.serial_port, self.s.serial_baud,
                    auto_reconnect=True, max_reconnect_attempts=5,
                )
            else:
                mc = await MeshCore.create_tcp(
                    self.s.host, self.s.port,
                    auto_reconnect=True, max_reconnect_attempts=5,
                )
        except Exception as exc:  # Verbindungsaufbau scheitert auf viele Arten
            self.error = f"Verbindung fehlgeschlagen: {exc}"
            log.warning(self.error)
            return False
        if mc is None:
            self.error = "Keine Antwort vom MeshCore-Node (falscher Host/Port?)"
            log.warning(self.error)
            return False

        mc.auto_update_contacts = True
        mc.subscribe(EventType.ADVERTISEMENT, self._on_advert)
        self._mc = mc
        try:
            await self.refresh_contacts()
        except Exception as exc:
            log.warning("Kontakte konnten nicht geladen werden: %s", exc)
        self.connected = True
        self.error = ""
        log.info("Verbunden mit %s", self.describe())
        return True

    async def _drop(self) -> None:
        mc, self._mc = self._mc, None
        if mc is not None:
            try:
                await mc.disconnect()
            except Exception:
                pass

    async def close(self) -> None:
        self._stopping = True
        await self._drop()
        self.connected = False

    # --- Befehle -----------------------------------------------------------

    async def refresh_contacts(self) -> None:
        if self._mc is None:
            return
        await self._mc.commands.get_contacts()

    async def request_telemetry(self, key: str, min_timeout: float) -> list[dict] | None:
        if self._mc is None:
            return None
        contact = self.get_contact(key)
        if contact is None:
            return None
        try:
            return await self._mc.commands.req_telemetry_sync(
                contact, timeout=0, min_timeout=min_timeout
            )
        except Exception as exc:
            log.warning("Telemetrie-Anfrage fehlgeschlagen: %s", exc)
            return None

    async def reset_path(self, key: str) -> tuple[bool, str]:
        from meshcore import EventType

        if self._mc is None:
            return False, "nicht verbunden"
        try:
            res = await self._mc.commands.reset_path(key)
        except Exception as exc:
            return False, str(exc)
        if res.type == EventType.ERROR:
            # Die Bibliothek löscht den Pfad lokal vorab – mit dem Gerät abgleichen.
            try:
                await self.refresh_contacts()
            except Exception:
                pass
            return False, f"Gerät lehnt Pfad-Reset ab ({res.payload})"
        return True, ""

    async def _on_advert(self, event) -> None:
        # Die Bibliothek aktualisiert die Kontakte selbst (auto_update_contacts);
        # wir holen sie sicherheitshalber vor dem Auswerten ab.
        key = None
        payload = getattr(event, "payload", None)
        if isinstance(payload, dict):
            key = payload.get("public_key")
        if not key or self._advert_cb is None:
            return
        try:
            await self._mc.ensure_contacts(follow=True)
        except Exception:
            pass
        await self._advert_cb(str(key).lower())
