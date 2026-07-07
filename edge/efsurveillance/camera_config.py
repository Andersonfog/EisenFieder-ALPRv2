"""Pulls this camera's settings from the backend and caches them.

The owner edits a camera's settings in the console (which vehicle types to
ignore, a confidence override, which details to capture, alerts on/off). The
edge fetches them here and the main loop enforces them locally.

Network is optional: with no backend configured, safe defaults apply (capture
everything). A failed fetch keeps the last known settings.
"""

from __future__ import annotations

import logging
import threading

logger = logging.getLogger(__name__)

DEFAULTS = {
    "excluded_types": [],
    "min_confidence": None,
    "capture_plate": True,
    "capture_occupants": True,
    "capture_company": True,
    "alerts_enabled": True,
    "quality_profile": "sharp_read",
    "enhance_plate": True,
    "lock_exposure": True,
    "edge_only": True,
}


class CameraConfigClient:
    def __init__(self, *, backend_url: str, camera_id: str, api_token: str = "",
                 refresh_seconds: float = 60.0) -> None:
        self.backend_url = (backend_url or "").rstrip("/")
        self.camera_id = camera_id
        self.api_token = api_token or ""
        self.refresh_seconds = refresh_seconds
        self._settings = dict(DEFAULTS)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if not self.backend_url:
            logger.info("Camera config: no backend; using defaults (capture everything).")
            return
        self._fetch()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        while not self._stop.is_set():
            self._stop.wait(self.refresh_seconds)
            if not self._stop.is_set():
                self._fetch()

    def _fetch(self) -> None:
        import requests

        url = f"{self.backend_url}/api/v1/cameras/{self.camera_id}/config"
        headers = {"X-Camera-Id": self.camera_id}
        if self.api_token:
            headers["Authorization"] = f"Bearer {self.api_token}"
        try:
            r = requests.get(url, headers=headers, timeout=10)
            if not r.ok:
                logger.debug("Camera config fetch HTTP %s", r.status_code)
                return
            data = r.json()
            merged = {k: data.get(k, v) for k, v in DEFAULTS.items()}
            with self._lock:
                changed = merged != self._settings
                self._settings = merged
            if changed:
                logger.info("Camera config updated: excluded=%s capture_plate=%s",
                            merged["excluded_types"], merged["capture_plate"])
        except Exception as exc:  # keep last known settings on any failure
            logger.debug("Camera config fetch failed: %s", exc)

    def get(self) -> dict:
        with self._lock:
            return dict(self._settings)

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)
