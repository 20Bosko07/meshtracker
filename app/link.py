"""Verbindung zu einem MeshCore-Companion (USB, WiFi/TCP oder MeshMonitor
Virtual Node) auf Basis der ``meshcore``-Bibliothek."""
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
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


@dataclass
class TelemetryReply:
    """Ergebnis einer Telemetrie-Anfrage. ``refused``: Das Gerät hat die Anfrage
    sofort abgelehnt (Wiederholen bringt nichts); sonst gab es nur keine Antwort."""

    lpp: list[dict] | None
    error: str | None = None
    refused: bool = False


REFUSAL_HINTS = {
    "ERR_CODE_BAD_STATE": "Gerät im falschen Zustand – bei MeshMonitor: Source im Receive-Only-Modus?",
    "ERR_CODE_UNSUPPORTED_CMD": "Befehl wird nicht unterstützt",
    "ERR_CODE_NOT_FOUND": "Kontakt dem Gerät unbekannt",
}


def describe_refusal(payload) -> str:
    code = payload.get("code_string") if isinstance(payload, dict) else None
    if not code and isinstance(payload, dict) and "error_code" in payload:
        code = f"Fehlercode {payload['error_code']}"
    hint = REFUSAL_HINTS.get(str(code))
    return f"Anfrage abgelehnt ({code or 'unbekannt'})" + (f": {hint}" if hint else "")


class Link(Protocol):
    """Was der Tracker-Dienst vom Funkgerät braucht."""

    connected: bool
    error: str

    def describe(self) -> dict: ...
    def contacts(self) -> dict[str, dict]: ...
    def get_contact(self, key: str) -> dict | None: ...
    async def refresh_contacts(self) -> None: ...
    async def request_telemetry(self, key: str, min_timeout: float) -> TelemetryReply: ...
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

    async def request_telemetry(self, key: str, min_timeout: float) -> TelemetryReply:
        from meshcore import EventType
        from meshcore.packets import BinaryReqType

        mc = self._mc
        if mc is None:
            return TelemetryReply(None, "nicht verbunden", refused=True)
        contact = self.get_contact(key)
        if contact is None:
            return TelemetryReply(None, "Kontakt unbekannt", refused=True)
        try:
            sent = await mc.commands.send_binary_req(
                contact, BinaryReqType.TELEMETRY, timeout=0, min_timeout=min_timeout
            )
            if sent.type == EventType.ERROR:
                reason = describe_refusal(sent.payload)
                log.warning("Telemetrie-Anfrage: %s", reason)
                return TelemetryReply(None, reason, refused=True)
            wait = max(sent.payload.get("suggested_timeout", 4000) / 800.0, min_timeout)
            event = await mc.dispatcher.wait_for_event(
                EventType.TELEMETRY_RESPONSE,
                attribute_filters={"tag": sent.payload["expected_ack"].hex()},
                timeout=wait,
            )
        except Exception as exc:
            log.warning("Telemetrie-Anfrage fehlgeschlagen: %s", exc)
            return TelemetryReply(None, f"Fehler: {exc}")
        if event is None:
            return TelemetryReply(None, f"keine Antwort innerhalb {wait:.0f} s")
        return TelemetryReply(event.payload["lpp"])

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
