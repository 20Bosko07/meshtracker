"""Configuration from environment variables (see .env.example)."""
from __future__ import annotations

import os
from dataclasses import dataclass


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    return int(raw) if raw else default


def _float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    return float(raw) if raw else default


@dataclass(frozen=True)
class Settings:
    # Connection to the MeshCore companion: "tcp" (WiFi companion or
    # MeshMonitor Virtual Node), "serial" (USB) or "sim" (simulator/demo).
    transport: str = "tcp"
    host: str = "127.0.0.1"
    port: int = 5000
    serial_port: str = "/dev/ttyACM0"
    serial_baud: int = 115200

    db_path: str = "/data/meshtracker.db"

    # Map tiles (the browser loads them straight from the provider). For heavy use please
    # configure your own tile server or a provider with a suitable plan.
    tile_url: str = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
    tile_attribution: str = "&copy; OpenStreetMap contributors"
    tile_max_zoom: int = 19

    # Optional password protection of the web interface (HTTP Basic).
    auth_user: str = ""
    auth_password: str = ""

    # Minimum time to wait for a reply (seconds). The firmware suggests its own
    # timeout depending on hops; this is only the lower bound. Behind MeshMonitor's
    # Virtual Node, that node itself waits up to 45 s for the tracker – giving up
    # earlier makes requests pile up and late replies get lost. With a direct
    # connection a smaller value is fine.
    path_timeout_floor: float = 48.0
    flood_timeout_floor: float = 48.0
    # How often to retry by flood after a request got no reply.
    flood_retries: int = 2
    flood_backoff: float = 5.0
    # Minimum gap between two mesh requests (spare the duty cycle).
    min_spacing: float = 10.0
    # After a completely failed poll, retry sooner (seconds).
    fail_retry: float = 180.0

    @classmethod
    def from_env(cls) -> "Settings":
        d = cls()
        return cls(
            transport=os.environ.get("MT_TRANSPORT", d.transport).strip().lower(),
            host=os.environ.get("MT_HOST", d.host).strip(),
            port=_int("MT_PORT", d.port),
            serial_port=os.environ.get("MT_SERIAL_PORT", d.serial_port).strip(),
            serial_baud=_int("MT_SERIAL_BAUD", d.serial_baud),
            db_path=os.environ.get("MT_DB_PATH", d.db_path).strip(),
            tile_url=os.environ.get("MT_TILE_URL", "").strip() or d.tile_url,
            tile_attribution=os.environ.get("MT_TILE_ATTRIBUTION", "").strip() or d.tile_attribution,
            tile_max_zoom=_int("MT_TILE_MAX_ZOOM", d.tile_max_zoom),
            auth_user=os.environ.get("MT_AUTH_USER", "").strip(),
            auth_password=os.environ.get("MT_AUTH_PASSWORD", ""),
            path_timeout_floor=_float("MT_PATH_TIMEOUT", d.path_timeout_floor),
            flood_timeout_floor=_float("MT_FLOOD_TIMEOUT", d.flood_timeout_floor),
            flood_retries=_int("MT_FLOOD_RETRIES", d.flood_retries),
            flood_backoff=_float("MT_FLOOD_BACKOFF", d.flood_backoff),
            min_spacing=_float("MT_MIN_SPACING", d.min_spacing),
            fail_retry=_float("MT_FAIL_RETRY", d.fail_retry),
        )
