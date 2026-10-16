"""SQLite persistence for trackers, positions, sensor values and the poll log."""
from __future__ import annotations

import sqlite3
import threading
import time
from typing import Any, Iterable

SCHEMA = """
CREATE TABLE IF NOT EXISTS trackers (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT NOT NULL,
    public_key   TEXT NOT NULL UNIQUE,
    interval_min INTEGER NOT NULL DEFAULT 10,
    route_mode   TEXT NOT NULL DEFAULT 'auto',
    enabled      INTEGER NOT NULL DEFAULT 1,
    created_at   INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS fixes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    tracker_id INTEGER NOT NULL REFERENCES trackers(id) ON DELETE CASCADE,
    ts         INTEGER NOT NULL,
    lat        REAL NOT NULL,
    lon        REAL NOT NULL,
    alt        REAL,
    source     TEXT NOT NULL,
    route      TEXT,
    hops       INTEGER,
    UNIQUE (tracker_id, source, ts)
);
CREATE INDEX IF NOT EXISTS fixes_tracker_ts ON fixes (tracker_id, ts);
CREATE TABLE IF NOT EXISTS sensors (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    tracker_id INTEGER NOT NULL REFERENCES trackers(id) ON DELETE CASCADE,
    ts         INTEGER NOT NULL,
    channel    INTEGER NOT NULL,
    type       TEXT NOT NULL,
    value      REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS sensors_tracker_ts ON sensors (tracker_id, ts);
CREATE TABLE IF NOT EXISTS polls (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    tracker_id  INTEGER NOT NULL REFERENCES trackers(id) ON DELETE CASCADE,
    ts          INTEGER NOT NULL,
    ok          INTEGER NOT NULL,
    has_gps     INTEGER NOT NULL DEFAULT 0,
    route       TEXT,
    attempts    TEXT NOT NULL DEFAULT '',
    duration_ms INTEGER NOT NULL DEFAULT 0,
    error       TEXT
);
CREATE INDEX IF NOT EXISTS polls_tracker_ts ON polls (tracker_id, ts);
"""


class Database:
    def __init__(self, path: str):
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _all(self, sql: str, args: Iterable[Any] = ()) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._conn.execute(sql, tuple(args)).fetchall()]

    def _one(self, sql: str, args: Iterable[Any] = ()) -> dict | None:
        rows = self._all(sql, args)
        return rows[0] if rows else None

    def _exec(self, sql: str, args: Iterable[Any] = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self._conn.execute(sql, tuple(args))
            self._conn.commit()
            return cur

    # --- Tracker -----------------------------------------------------------

    def add_tracker(self, name: str, public_key: str, interval_min: int, route_mode: str) -> dict:
        cur = self._exec(
            "INSERT INTO trackers (name, public_key, interval_min, route_mode, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (name, public_key, interval_min, route_mode, int(time.time())),
        )
        return self.get_tracker(cur.lastrowid)  # type: ignore[arg-type]

    def update_tracker(self, tracker_id: int, **fields: Any) -> dict | None:
        allowed = {"name", "interval_min", "route_mode", "enabled"}
        sets = {k: v for k, v in fields.items() if k in allowed and v is not None}
        if sets:
            cols = ", ".join(f"{k} = ?" for k in sets)
            self._exec(f"UPDATE trackers SET {cols} WHERE id = ?", (*sets.values(), tracker_id))
        return self.get_tracker(tracker_id)

    def delete_tracker(self, tracker_id: int) -> bool:
        return self._exec("DELETE FROM trackers WHERE id = ?", (tracker_id,)).rowcount > 0

    def get_tracker(self, tracker_id: int) -> dict | None:
        return self._one("SELECT * FROM trackers WHERE id = ?", (tracker_id,))

    def get_tracker_by_key(self, public_key: str) -> dict | None:
        return self._one("SELECT * FROM trackers WHERE public_key = ?", (public_key,))

    def list_trackers(self) -> list[dict]:
        return self._all("SELECT * FROM trackers ORDER BY id")

    # --- Positions --------------------------------------------------------

    def add_fix(
        self,
        tracker_id: int,
        ts: int,
        lat: float,
        lon: float,
        alt: float | None,
        source: str,
        route: str | None = None,
        hops: int | None = None,
    ) -> bool:
        cur = self._exec(
            "INSERT OR IGNORE INTO fixes (tracker_id, ts, lat, lon, alt, source, route, hops)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (tracker_id, ts, lat, lon, alt, source, route, hops),
        )
        return cur.rowcount > 0

    def latest_fix(self, tracker_id: int) -> dict | None:
        return self._one(
            "SELECT * FROM fixes WHERE tracker_id = ? ORDER BY ts DESC, id DESC LIMIT 1",
            (tracker_id,),
        )

    def fixes(self, tracker_id: int, since: int = 0, limit: int = 5000) -> list[dict]:
        rows = self._all(
            "SELECT * FROM (SELECT * FROM fixes WHERE tracker_id = ? AND ts >= ?"
            " ORDER BY ts DESC, id DESC LIMIT ?) ORDER BY ts, id",
            (tracker_id, since, limit),
        )
        return rows

    # --- Sensors ----------------------------------------------------------

    def add_sensors(self, tracker_id: int, ts: int, readings: Iterable[tuple[int, str, float]]) -> None:
        with self._lock:
            self._conn.executemany(
                "INSERT INTO sensors (tracker_id, ts, channel, type, value) VALUES (?, ?, ?, ?, ?)",
                [(tracker_id, ts, c, t, v) for c, t, v in readings],
            )
            self._conn.commit()

    def latest_sensors(self, tracker_id: int) -> list[dict]:
        return self._all(
            "SELECT s.channel, s.type, s.value, s.ts FROM sensors s"
            " JOIN (SELECT channel, type, MAX(ts) AS ts FROM sensors WHERE tracker_id = ?"
            "       GROUP BY channel, type) m"
            " ON s.channel = m.channel AND s.type = m.type AND s.ts = m.ts"
            " WHERE s.tracker_id = ? GROUP BY s.channel, s.type ORDER BY s.channel, s.type",
            (tracker_id, tracker_id),
        )

    def series(self, tracker_id: int, since: int = 0, limit: int = 5000) -> list[dict]:
        """History per measurement (sensors + GPS altitude) as [[ts, value], …]."""
        grouped: dict[tuple[str, int], list[list[float]]] = {}
        rows = self._all(
            "SELECT channel, type, ts, value FROM (SELECT channel, type, ts, value FROM sensors"
            " WHERE tracker_id = ? AND ts >= ? ORDER BY ts DESC LIMIT ?) ORDER BY ts",
            (tracker_id, since, limit),
        )
        for r in rows:
            grouped.setdefault((r["type"], r["channel"]), []).append([r["ts"], r["value"]])
        out = [
            {"key": f"{t}:{c}", "type": t, "channel": c, "points": pts}
            for (t, c), pts in sorted(grouped.items())
        ]
        alt = self._all(
            "SELECT ts, alt FROM (SELECT ts, alt FROM fixes WHERE tracker_id = ? AND ts >= ?"
            " AND alt IS NOT NULL AND source = 'telemetry' ORDER BY ts DESC LIMIT ?) ORDER BY ts",
            (tracker_id, since, limit),
        )
        if alt:
            out.append({"key": "gps_altitude:0", "type": "gps_altitude", "channel": 0,
                        "points": [[r["ts"], r["alt"]] for r in alt]})
        return out

    # --- Poll log -------------------------------------------------

    def add_poll(
        self,
        tracker_id: int,
        ts: int,
        ok: bool,
        has_gps: bool,
        route: str | None,
        attempts: str,
        duration_ms: int,
        error: str | None,
    ) -> None:
        self._exec(
            "INSERT INTO polls (tracker_id, ts, ok, has_gps, route, attempts, duration_ms, error)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (tracker_id, ts, int(ok), int(has_gps), route, attempts, duration_ms, error),
        )

    def recent_polls(self, tracker_id: int, limit: int = 20) -> list[dict]:
        return self._all(
            "SELECT * FROM polls WHERE tracker_id = ? ORDER BY ts DESC, id DESC LIMIT ?",
            (tracker_id, limit),
        )

    def prune(self, keep_days: int = 30, sensor_days: int = 365) -> None:
        """Delete old poll-log and sensor entries (positions are kept)."""
        now = int(time.time())
        self._exec("DELETE FROM polls WHERE ts < ?", (now - keep_days * 86400,))
        self._exec("DELETE FROM sensors WHERE ts < ?", (now - sensor_days * 86400,))
