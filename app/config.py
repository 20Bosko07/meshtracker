"""Konfiguration aus Umgebungsvariablen (siehe docker-compose.yml)."""
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
    # Verbindung zum MeshCore-Companion: "tcp" (Node/WiFi-Companion oder
    # MeshMonitor Virtual Node), "serial" (USB) oder "sim" (Simulator/Demo).
    transport: str = "tcp"
    host: str = "127.0.0.1"
    port: int = 5000
    serial_port: str = "/dev/ttyACM0"
    serial_baud: int = 115200

    db_path: str = "/data/meshtracker.db"

    # Optionaler Passwortschutz der Weboberfläche (HTTP Basic).
    auth_user: str = ""
    auth_password: str = ""

    # Mindestwartezeit auf eine Antwort (Sekunden). Die Firmware liefert einen
    # eigenen Timeout-Vorschlag je nach Hops; das hier ist nur die Untergrenze.
    # Über den MeshMonitor Virtual Node wartet dieser selbst bis zu 45 s auf den
    # Tracker – gibt man früher auf, stapeln sich die Anfragen und späte
    # Antworten gehen verloren. Bei direkter Anbindung darf der Wert kleiner sein.
    path_timeout_floor: float = 48.0
    flood_timeout_floor: float = 48.0
    # Wie oft nach einem fehlgeschlagenen Pfad-Versuch per Flood wiederholt wird.
    flood_retries: int = 2
    flood_backoff: float = 5.0
    # Mindestabstand zwischen zwei Mesh-Anfragen (Duty-Cycle schonen).
    min_spacing: float = 10.0
    # Nach komplett fehlgeschlagener Abfrage früher erneut versuchen (Sekunden).
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
            auth_user=os.environ.get("MT_AUTH_USER", "").strip(),
            auth_password=os.environ.get("MT_AUTH_PASSWORD", ""),
            path_timeout_floor=_float("MT_PATH_TIMEOUT", d.path_timeout_floor),
            flood_timeout_floor=_float("MT_FLOOD_TIMEOUT", d.flood_timeout_floor),
            flood_retries=_int("MT_FLOOD_RETRIES", d.flood_retries),
            flood_backoff=_float("MT_FLOOD_BACKOFF", d.flood_backoff),
            min_spacing=_float("MT_MIN_SPACING", d.min_spacing),
            fail_retry=_float("MT_FAIL_RETRY", d.fail_retry),
        )
