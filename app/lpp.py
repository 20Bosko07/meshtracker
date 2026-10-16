"""Evaluation of the Cayenne LPP telemetry a MeshCore node sends back in reply to a
telemetry request (already decoded by the meshcore library into a list of
``{"channel", "type", "value"}``)."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Fix:
    lat: float
    lon: float
    alt: float | None


@dataclass
class Reading:
    channel: int
    type: str
    value: float


def _valid_fix(lat: float, lon: float) -> bool:
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return False
    # A tracker without a GPS fix reports (0, 0).
    return not (abs(lat) < 1e-6 and abs(lon) < 1e-6)


def extract(lpp: list[dict] | None) -> tuple[Fix | None, list[Reading]]:
    """Separate the GPS position from the other sensor values."""
    fix: Fix | None = None
    readings: list[Reading] = []
    seen: dict[tuple[int, str], int] = {}

    def add(channel: int, kind: str, value: float) -> None:
        # The firmware appends e.g. the chip temperature on the same channel as the
        # temperature sensor. The first value keeps the name, further ones get _2, _3 …
        n = seen[(channel, kind)] = seen.get((channel, kind), 0) + 1
        readings.append(Reading(channel, kind if n == 1 else f"{kind}_{n}", value))

    for item in lpp or []:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("type", ""))
        channel = int(item.get("channel", 0) or 0)
        value = item.get("value")
        if kind == "gps" and isinstance(value, dict):
            try:
                lat = float(value["latitude"])
                lon = float(value["longitude"])
            except (KeyError, TypeError, ValueError):
                continue
            if _valid_fix(lat, lon) and fix is None:
                alt = value.get("altitude")
                fix = Fix(lat, lon, float(alt) if alt is not None else None)
        elif isinstance(value, bool):
            add(channel, kind, float(value))
        elif isinstance(value, (int, float)):
            add(channel, kind, float(value))
        elif isinstance(value, dict):
            for sub, v in value.items():
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    add(channel, f"{kind}.{sub}", float(v))
    return fix, readings
