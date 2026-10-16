"""Connection to a MeshCore companion (USB, WiFi/TCP or MeshMonitor's
Virtual Node), built on the ``meshcore`` library."""
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
    """-1 = flood (no path known), 0 = direct, n = n hops."""
    if not contact:
        return -1
    try:
        return int(contact.get("out_path_len", -1))
    except (TypeError, ValueError):
        return -1


@dataclass
class TelemetryReply:
    """Result of a telemetry request. ``refused``: the device rejected the request
    right away (retrying is pointless); otherwise there was simply no reply."""

    lpp: list[dict] | None
    error: str | None = None
    refused: bool = False


REFUSAL_HINTS = {
    "ERR_CODE_BAD_STATE": "device in the wrong state – with MeshMonitor: is the source in receive-only mode?",
    "ERR_CODE_UNSUPPORTED_CMD": "command not supported",
    "ERR_CODE_NOT_FOUND": "contact unknown to the device",
}


def describe_refusal(payload) -> str:
    code = payload.get("code_string") if isinstance(payload, dict) else None
    if not code and isinstance(payload, dict) and "error_code" in payload:
        code = f"error code {payload['error_code']}"
    hint = REFUSAL_HINTS.get(str(code))
    return f"Request refused ({code or 'unknown'})" + (f": {hint}" if hint else "")


class Link(Protocol):
    """What the tracker service needs from the radio."""

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
    """Keeps the connection alive (reconnects with backoff)."""

    def __init__(self, settings: Settings):
        self.s = settings
        self.connected = False
        self.error = ""
        self._mc = None
        self._advert_cb: AdvertCallback | None = None
        self._stopping = False
        # Older MeshMonitor Virtual Nodes do not know BinaryReq → use the old command.
        self._legacy_telemetry = False

    # --- State -----------------------------------------------------------

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

    # --- Connection --------------------------------------------------------

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
        except Exception as exc:  # connecting can fail in many ways
            self.error = f"Connection failed: {exc}"
            log.warning(self.error)
            return False
        if mc is None:
            self.error = "No response from the MeshCore node (wrong host/port?)"
            log.warning(self.error)
            return False

        mc.auto_update_contacts = True
        self._legacy_telemetry = False
        mc.subscribe(EventType.ADVERTISEMENT, self._on_advert)
        self._mc = mc
        try:
            await self.refresh_contacts()
        except Exception as exc:
            log.warning("Could not load contacts: %s", exc)
        self.connected = True
        self.error = ""
        log.info("Connected to %s", self.describe())
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

    # --- Commands -----------------------------------------------------------

    async def refresh_contacts(self) -> None:
        if self._mc is None:
            return
        await self._mc.commands.get_contacts()

    async def request_telemetry(self, key: str, min_timeout: float) -> TelemetryReply:
        mc = self._mc
        if mc is None:
            return TelemetryReply(None, "not connected", refused=True)
        contact = self.get_contact(key)
        if contact is None:
            return TelemetryReply(None, "unknown contact", refused=True)
        try:
            if not self._legacy_telemetry:
                reply = await self._telemetry_binary(mc, contact, min_timeout)
                if not (reply.refused and "UNSUPPORTED_CMD" in (reply.error or "")):
                    return reply
                log.info("Device does not know BinaryReq – switching to the older telemetry command")
                self._legacy_telemetry = True
            return await self._telemetry_legacy(mc, contact, min_timeout)
        except Exception as exc:
            log.warning("Telemetry request failed: %s", exc)
            return TelemetryReply(None, f"Error: {exc}")

    async def _telemetry_binary(self, mc, contact: dict, min_timeout: float) -> TelemetryReply:
        """Current way: BinaryReq(TELEMETRY), reply matched by tag."""
        from meshcore import EventType
        from meshcore.packets import BinaryReqType

        sent = await mc.commands.send_binary_req(
            contact, BinaryReqType.TELEMETRY, timeout=0, min_timeout=min_timeout
        )
        if sent.type == EventType.ERROR:
            reason = describe_refusal(sent.payload)
            log.warning("Telemetry request: %s", reason)
            return TelemetryReply(None, reason, refused=True)
        wait = max(sent.payload.get("suggested_timeout", 4000) / 800.0, min_timeout)
        event = await mc.dispatcher.wait_for_event(
            EventType.TELEMETRY_RESPONSE,
            attribute_filters={"tag": sent.payload["expected_ack"].hex()},
            timeout=wait,
        )
        if event is None:
            return TelemetryReply(None, f"no reply within {wait:.0f} s")
        return TelemetryReply(event.payload["lpp"])

    async def _telemetry_legacy(self, mc, contact: dict, min_timeout: float) -> TelemetryReply:
        """Older way (SEND_TELEMETRY_REQ 0x27): the reply arrives as a push carrying the
        6-byte key prefix. Subscribe before sending so a fast reply is not lost."""
        from meshcore import EventType

        key = bytes.fromhex(contact["public_key"])
        got: asyncio.Future = asyncio.get_running_loop().create_future()

        async def on_response(event) -> None:
            if not got.done():
                got.set_result(event.payload.get("lpp"))

        sub = mc.subscribe(EventType.TELEMETRY_RESPONSE, on_response,
                           attribute_filters={"pubkey_prefix": key[:6].hex()})
        try:
            sent = await mc.commands.send(b"\x27\x00\x00\x00" + key, [EventType.MSG_SENT, EventType.ERROR])
            if sent.type == EventType.ERROR:
                reason = describe_refusal(sent.payload)
                log.warning("Telemetry request (old command): %s", reason)
                return TelemetryReply(None, reason, refused=True)
            wait = max(sent.payload.get("suggested_timeout", 4000) / 800.0, min_timeout)
            try:
                lpp = await asyncio.wait_for(got, wait)
            except asyncio.TimeoutError:
                return TelemetryReply(None, f"no reply within {wait:.0f} s")
            return TelemetryReply(lpp)
        finally:
            sub.unsubscribe()

    async def reset_path(self, key: str) -> tuple[bool, str]:
        from meshcore import EventType

        if self._mc is None:
            return False, "not connected"
        try:
            res = await self._mc.commands.reset_path(key)
        except Exception as exc:
            return False, str(exc)
        if res.type == EventType.ERROR:
            # The library clears the path locally up front – resync with the device.
            try:
                await self.refresh_contacts()
            except Exception:
                pass
            return False, f"Device refuses path reset ({res.payload})"
        return True, ""

    async def _on_advert(self, event) -> None:
        # The library updates contacts itself (auto_update_contacts); we fetch them
        # once more before evaluating, to be safe.
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
