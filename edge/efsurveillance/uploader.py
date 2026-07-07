"""Store-and-forward uploader.

Events are always written to the local SQLite buffer first (event_logger). This
uploader drains the unsynced queue to the central backend whenever the network
is up:

    * On success it marks the event ``synced`` so it's never sent twice.
    * On a connectivity failure it stops and retries next poll — nothing is lost,
      and it auto-resyncs the moment the link returns.
    * Uploads are idempotent on ``event_uuid`` (the backend treats a duplicate as
      success), so a flaky connection can't create duplicates.
    * A per-event attempt budget skips "poison" events so one bad event can't
      wedge the whole queue.

Each event is one HTTP POST: a JSON metadata field + the scene still + an
optional plate crop. Never video, never a stream.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

VEHICLES_ENDPOINT = "/api/v1/vehicles"


class Uploader:
    def __init__(self, cfg, events, *, camera_id: str) -> None:
        self.cfg = cfg
        self.events = events
        self.camera_id = camera_id
        self.backend_url = (cfg.backend_url or os.getenv("BACKEND_URL", "")).rstrip("/")
        self.api_token = os.getenv("BACKEND_API_TOKEN", "").strip()
        self._stop = threading.Event()
        self._wake = threading.Event()   # set by kick() → sync NOW, not next poll
        self._thread: Optional[threading.Thread] = None
        self.online = False

    def kick(self) -> None:
        """Wake the sync loop immediately (a fresh event just landed) so a new
        vehicle reaches the console in well under a second instead of waiting
        for the next poll."""
        self._wake.set()

    # -- lifecycle --------------------------------------------------------- #
    def start(self) -> None:
        if not self.cfg.enabled:
            logger.info("Uploader disabled (events buffer locally only).")
            return
        if not self.backend_url:
            logger.warning(
                "Uploader enabled but no backend URL (uploader.backend_url or "
                "BACKEND_URL). Events will buffer locally until configured."
            )
            return
        logger.info("Uploader: syncing to %s every %.0fs",
                    self.backend_url + VEHICLES_ENDPOINT, self.cfg.poll_interval_seconds)
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()  # unblock the loop so shutdown doesn't wait a full poll
        if self._thread:
            self._thread.join(timeout=self.cfg.request_timeout_seconds + 2)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.sync_once()
            except Exception as exc:  # the sync thread must never die
                logger.warning("Uploader cycle error: %s", exc)
            self._wake.wait(timeout=self.cfg.poll_interval_seconds)
            self._wake.clear()

    # -- draining ---------------------------------------------------------- #
    def sync_once(self) -> int:
        if not self.backend_url:
            return 0
        pending = self.events.get_unsynced(
            limit=self.cfg.batch_size, max_attempts=self.cfg.max_attempts
        )
        if not pending:
            return 0

        synced_ids: list[int] = []
        uploaded_files: list[str] = []
        for event in pending:
            if self._stop.is_set():
                break
            ok, offline = self._upload_one(event)
            if ok:
                synced_ids.append(event["id"])
                for key in ("image_path", "plate_image_path", "profile_image_path"):
                    if event.get(key):
                        uploaded_files.append(event[key])
            else:
                self.events.record_attempt(event["id"])
                if offline:
                    self.online = False
                    logger.info("Uploader: link down; %d event(s) buffered, will retry.",
                                self.events.count_unsynced())
                    break

        if synced_ids:
            self.events.mark_synced(synced_ids)
            self.online = True
            if self.cfg.delete_local_after_upload:
                self._delete_local(uploaded_files)
            logger.info("Uploader: synced %d event(s); %d remaining.",
                        len(synced_ids), self.events.count_unsynced())
        return len(synced_ids)

    def _delete_local(self, paths: list[str]) -> None:
        for p in paths:
            try:
                path = Path(p)
                if path.is_file():
                    path.unlink()
            except Exception as exc:  # never let cleanup break syncing
                logger.debug("Could not delete local file %s: %s", p, exc)

    def build_metadata(self, event: dict[str, Any]) -> dict[str, Any]:
        """Map a local DB row to the backend's VehicleEventMetadata shape."""
        return {
            "event_uuid": event["event_uuid"],
            "camera_id": event["camera_id"],
            "captured_at": event["captured_at"],
            "direction": event.get("direction") or "unknown",
            "plate_text": event.get("plate_text"),
            "plate_confidence": event.get("plate_confidence"),
            "plate_region": event.get("plate_region"),
            "vehicle_type": event.get("vehicle_type"),
            "vehicle_make": event.get("vehicle_make"),
            "vehicle_model": event.get("vehicle_model"),
            "vehicle_color": event.get("vehicle_color"),
            "occupant_count": event.get("occupant_count"),
            "is_commercial": bool(event.get("is_commercial")),
            "company_name": event.get("company_name"),
            "confidence": event.get("confidence") or 0.0,
            "pending": bool(event.get("pending")),
            "metadata": json.loads(event["metadata"]) if event.get("metadata") else None,
        }

    def _upload_one(self, event: dict[str, Any]) -> tuple[bool, bool]:
        """Upload a single event. Returns (success, offline)."""
        import requests

        url = self.backend_url + VEHICLES_ENDPOINT
        headers = {"X-Camera-Id": self.camera_id}
        if self.api_token:
            headers["Authorization"] = f"Bearer {self.api_token}"

        opened: list[Any] = []
        try:
            files: dict[str, Any] = {"metadata": (None, json.dumps(self.build_metadata(event)))}
            for field, key in (("image", "image_path"),
                               ("plate_image", "plate_image_path"),
                               ("profile_image", "profile_image_path")):
                path = event.get(key)
                if path and Path(path).exists():
                    fh = open(path, "rb")
                    opened.append(fh)
                    files[field] = (Path(path).name, fh, "image/jpeg")

            resp = requests.post(url, files=files, headers=headers,
                                 timeout=self.cfg.request_timeout_seconds)
            if resp.status_code < 300 or resp.status_code == 409:
                return True, False
            logger.warning("Uploader: event %s rejected (HTTP %s): %s",
                           event["event_uuid"], resp.status_code, resp.text[:200])
            return False, False
        except requests.exceptions.RequestException as exc:
            logger.debug("Uploader: network error for %s: %s", event["event_uuid"], exc)
            return False, True
        finally:
            for fh in opened:
                fh.close()
