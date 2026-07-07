"""Local SQLite buffer for vehicle events (store-and-forward).

Every vehicle that survives debouncing becomes a row here plus up to two stills
on disk (the scene + a plate crop). This is the on-device source of truth: the
``synced`` flag lets the uploader push events when the network is up and never
lose one while it's down.

Stdlib ``sqlite3`` only — safe to run on a Pi with no extra packages.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS vehicle_events (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    event_uuid       TEXT    UNIQUE NOT NULL,
    camera_id        TEXT    NOT NULL,
    captured_at      TEXT    NOT NULL,
    direction        TEXT    NOT NULL DEFAULT 'unknown',
    plate_text       TEXT,
    plate_confidence REAL,
    plate_region     TEXT,
    vehicle_type     TEXT,
    vehicle_make     TEXT,
    vehicle_model    TEXT,
    vehicle_color    TEXT,
    occupant_count   INTEGER,
    is_commercial    INTEGER NOT NULL DEFAULT 0,
    company_name     TEXT,
    confidence       REAL    NOT NULL DEFAULT 0,
    image_path       TEXT,
    plate_image_path TEXT,
    profile_image_path TEXT,
    metadata         TEXT,
    pending          INTEGER NOT NULL DEFAULT 0,
    synced           INTEGER NOT NULL DEFAULT 0,
    upload_attempts  INTEGER NOT NULL DEFAULT 0,
    last_attempt_at  TEXT,
    created_at       TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ve_synced      ON vehicle_events(synced);
CREATE INDEX IF NOT EXISTS idx_ve_captured_at ON vehicle_events(captured_at);
"""


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class EventLogger:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._migrate()
        self._conn.commit()
        logger.info("Event DB ready at %s", self.db_path)

    def _migrate(self) -> None:
        """Add columns introduced after a DB was first created (idempotent)."""
        present = {r["name"] for r in
                   self._conn.execute("PRAGMA table_info(vehicle_events)")}
        if "pending" not in present:
            self._conn.execute(
                "ALTER TABLE vehicle_events ADD COLUMN pending INTEGER NOT NULL DEFAULT 0")
        if "profile_image_path" not in present:
            self._conn.execute(
                "ALTER TABLE vehicle_events ADD COLUMN profile_image_path TEXT")

    # -- writes ------------------------------------------------------------ #
    def log_vehicle(
        self,
        *,
        camera_id: str,
        captured_at: Optional[str] = None,
        direction: str = "unknown",
        plate_text: Optional[str] = None,
        plate_confidence: Optional[float] = None,
        plate_region: Optional[str] = None,
        vehicle_type: Optional[str] = None,
        vehicle_make: Optional[str] = None,
        vehicle_model: Optional[str] = None,
        vehicle_color: Optional[str] = None,
        occupant_count: Optional[int] = None,
        is_commercial: bool = False,
        company_name: Optional[str] = None,
        confidence: float = 0.0,
        image_path: Optional[str] = None,
        plate_image_path: Optional[str] = None,
        profile_image_path: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
        event_uuid: Optional[str] = None,
        pending: bool = False,
    ) -> dict[str, Any]:
        """Insert one vehicle event — or UPDATE it in place when an event with
        the same ``event_uuid`` already exists (the instant "vehicle arrived"
        row being enriched by the final commit). An update resets ``synced`` so
        the uploader pushes the new data, and keeps the original captured_at
        (the moment the vehicle was first seen keeps its spot in the log)."""
        row = {
            "event_uuid": event_uuid or str(uuid.uuid4()),
            "camera_id": camera_id,
            "captured_at": captured_at or _utcnow_iso(),
            "direction": direction or "unknown",
            "plate_text": plate_text,
            "plate_confidence": plate_confidence,
            "plate_region": plate_region,
            "vehicle_type": vehicle_type,
            "vehicle_make": vehicle_make,
            "vehicle_model": vehicle_model,
            "vehicle_color": vehicle_color,
            "occupant_count": occupant_count,
            "is_commercial": 1 if is_commercial else 0,
            "company_name": company_name,
            "confidence": float(confidence),
            "image_path": image_path,
            "plate_image_path": plate_image_path,
            "profile_image_path": profile_image_path,
            "metadata": json.dumps(metadata) if metadata else None,
            "pending": 1 if pending else 0,
            "synced": 0,
            "created_at": _utcnow_iso(),
        }

        # If this replaces a provisional row, its old stills become orphans on
        # disk (the new commit wrote fresh files) — collect them for cleanup.
        old = self._conn.execute(
            "SELECT image_path, plate_image_path, profile_image_path "
            "FROM vehicle_events WHERE event_uuid = ?", (row["event_uuid"],)
        ).fetchone()

        cols = ", ".join(row.keys())
        placeholders = ", ".join(f":{k}" for k in row)
        # On conflict: update everything EXCEPT captured_at/created_at, and
        # reset the sync state so the enriched event is uploaded again.
        updatable = [k for k in row
                     if k not in ("event_uuid", "captured_at", "created_at")]
        sets = ", ".join(f"{k} = excluded.{k}" for k in updatable)
        cur = self._conn.execute(
            f"INSERT INTO vehicle_events ({cols}) VALUES ({placeholders}) "
            f"ON CONFLICT(event_uuid) DO UPDATE SET {sets}, "
            f"upload_attempts = 0, last_attempt_at = NULL",
            row,
        )
        self._conn.commit()
        got = self._conn.execute(
            "SELECT id FROM vehicle_events WHERE event_uuid = ?",
            (row["event_uuid"],),
        ).fetchone()
        row["id"] = got["id"] if got else cur.lastrowid

        if old is not None:
            for old_path, new_path in ((old["image_path"], image_path),
                                       (old["plate_image_path"], plate_image_path),
                                       (old["profile_image_path"], profile_image_path)):
                if old_path and old_path != new_path:
                    try:
                        Path(old_path).unlink(missing_ok=True)
                    except Exception:
                        pass  # cleanup must never break logging
        return row

    def mark_synced(self, event_ids: list[int]) -> None:
        if not event_ids:
            return
        self._conn.executemany(
            "UPDATE vehicle_events SET synced = 1 WHERE id = ?", [(i,) for i in event_ids]
        )
        self._conn.commit()

    def record_attempt(self, event_id: int) -> None:
        self._conn.execute(
            "UPDATE vehicle_events SET upload_attempts = upload_attempts + 1, "
            "last_attempt_at = ? WHERE id = ?",
            (_utcnow_iso(), event_id),
        )
        self._conn.commit()

    # -- reads ------------------------------------------------------------- #
    def get_unsynced(self, limit: int = 100, max_attempts: Optional[int] = None) -> list[dict[str, Any]]:
        if max_attempts is None:
            cur = self._conn.execute(
                "SELECT * FROM vehicle_events WHERE synced = 0 ORDER BY id ASC LIMIT ?",
                (limit,),
            )
        else:
            cur = self._conn.execute(
                "SELECT * FROM vehicle_events WHERE synced = 0 AND upload_attempts < ? "
                "ORDER BY id ASC LIMIT ?",
                (max_attempts, limit),
            )
        return [dict(r) for r in cur.fetchall()]

    def recent(self, limit: int = 20) -> list[dict[str, Any]]:
        cur = self._conn.execute(
            "SELECT * FROM vehicle_events ORDER BY id DESC LIMIT ?", (limit,)
        )
        return [dict(r) for r in cur.fetchall()]

    def count(self) -> int:
        return int(self._conn.execute("SELECT COUNT(*) FROM vehicle_events").fetchone()[0])

    def count_unsynced(self) -> int:
        return int(self._conn.execute(
            "SELECT COUNT(*) FROM vehicle_events WHERE synced = 0"
        ).fetchone()[0])

    def count_by_type(self) -> dict[str, int]:
        cur = self._conn.execute(
            "SELECT vehicle_type, COUNT(*) AS n FROM vehicle_events "
            "GROUP BY vehicle_type ORDER BY n DESC"
        )
        return {(r["vehicle_type"] or "unknown"): int(r["n"]) for r in cur.fetchall()}

    # -- lifecycle --------------------------------------------------------- #
    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:  # pragma: no cover - defensive
            pass

    def __enter__(self) -> "EventLogger":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
