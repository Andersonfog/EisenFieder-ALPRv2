"""Live preview pusher.

Sends a low-frame-rate JPEG preview to the backend so the owner can see the
camera's current view in the console (to check the angle when installing).

Design goals:
  * Never slow the detection loop — encoding/uploading runs in a background
    thread and always sends the *latest* submitted frame, dropping any it
    couldn't keep up with.
  * Never crash the unit — every failure is swallowed (best-effort preview).
  * Cheap — frames are downscaled and JPEG-compressed before sending.

On a real camera the actual frame is encoded; in mock mode a synthetic "live"
scene is drawn so the feature is demonstrable on a laptop.
"""

from __future__ import annotations

import io
import logging
import threading
import time
from typing import Any, Optional

from .camera import SyntheticFrame, frame_size

logger = logging.getLogger(__name__)

LIVE_ENDPOINT = "/api/v1/cameras/{camera_id}/live"
LIVE_STREAM_ENDPOINT = "/api/v1/cameras/{camera_id}/live/stream"

# After this many consecutive stream-connection failures, drop back to the
# slower-but-simple one-POST-per-frame mode (e.g. an older backend).
_STREAM_FAILURES_BEFORE_FALLBACK = 5


def frame_packet(jpeg: bytes, stats: Optional[dict] = None) -> bytes:
    """One frame on the edge->backend live stream.

    Wire format (one line of ASCII, then the raw JPEG):

        EFSF <jpeg_length> <capture_fps> <detect_fps> [key=value...]\\n<jpeg bytes>

    A single held-open upload carrying these packets replaces one whole HTTP
    request per frame — no per-frame headers, handshakes or waits.
    """
    stats = stats or {}
    cap = stats.get("capture_fps") or 0
    det = stats.get("detect_fps") or 0
    extras = []
    for key in (
        "profile",
        "source_fps",
        "frame_width",
        "frame_height",
        "live_quality",
        "cpu_temp_c",
        "queued",
    ):
        value = stats.get(key)
        if value is not None and value != "":
            extras.append(f"{key}={str(value).replace(' ', '_')}")
    extra = (" " + " ".join(extras)) if extras else ""
    return f"EFSF {len(jpeg)} {cap} {det}{extra}\n".encode() + jpeg

# Detection boxes older than this aren't drawn: if the detector stalls, a
# frozen box floating over live video would lie about what the AI sees.
_OVERLAY_MAX_AGE_SECONDS = 1.5
# BGR box colours per kind of thing detected.
_OVERLAY_COLORS = {"vehicle": (90, 220, 90), "person": (60, 170, 255)}


class LivePusher:
    def __init__(self, cfg, *, camera_id: str, backend_url: str, api_token: str,
                 stats_provider=None, overlay_provider=None) -> None:
        self.camera_id = camera_id
        self.backend_url = (backend_url or "").rstrip("/")
        self.api_token = api_token
        self.stats_provider = stats_provider
        # Callable returning the newest detections to draw over the preview:
        # {"ts": monotonic, "frame_wh": (w, h), "items": [(bbox, label, kind)]}
        self.overlay_provider = overlay_provider
        self.annotate = bool(getattr(cfg, "live_annotate", True))
        self.fps = max(0.5, float(getattr(cfg, "live_fps", 4.0)))
        self.max_width = int(getattr(cfg, "live_max_width", 640))
        self.jpeg_quality = max(40, min(92, int(getattr(cfg, "live_jpeg_quality", 70))))
        self.timeout = float(getattr(cfg, "request_timeout_seconds", 20.0))
        # "stream" = one held-open upload (fastest); "post" = one request per
        # frame (fallback, and kept for older backends).
        self.mode = str(getattr(cfg, "live_mode", "stream") or "stream").lower()
        self._stream_failures = 0
        self._interval = 1.0 / self.fps

        enabled = bool(getattr(cfg, "live_enabled", False))
        self.active = enabled and bool(self.backend_url)
        if enabled and not self.backend_url:
            logger.warning("Live preview enabled but no backend URL; disabling.")

        self._pending: Optional[Any] = None
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._tick = 0
        self._warned = False
        # One persistent HTTP connection (created in the worker thread): a new
        # TCP handshake per frame was costing more than the frame itself.
        self._session = None

    # -- lifecycle --------------------------------------------------------- #
    def start(self) -> None:
        if not self.active:
            return
        logger.info("Live preview: pushing ~%.0f fps to %s", self.fps,
                    self.backend_url + LIVE_ENDPOINT.format(camera_id=self.camera_id))
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def submit(self, frame: Any) -> None:
        """Hand the newest frame to the worker (non-blocking; drops stale ones)."""
        if not self.active:
            return
        with self._lock:
            self._pending = frame
        self._wake.set()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout=self.timeout + 1)

    # -- worker ------------------------------------------------------------ #
    def _loop(self) -> None:
        while not self._stop.is_set():
            if self.mode == "stream":
                try:
                    self._run_stream()
                    self._stream_failures = 0
                except Exception as exc:
                    self._stream_failures += 1
                    logger.debug("Live stream dropped (%d): %s",
                                 self._stream_failures, exc)
                    if self._stream_failures >= _STREAM_FAILURES_BEFORE_FALLBACK:
                        logger.warning(
                            "Live stream keeps failing - falling back to "
                            "one-POST-per-frame preview.")
                        self.mode = "post"
                    else:
                        self._stop.wait(timeout=1.0)
            else:
                self._post_one()

    def _next_frame(self) -> Optional[Any]:
        """Block until the newest un-sent frame is available (or shutdown)."""
        self._wake.wait(timeout=1.0)
        self._wake.clear()
        if self._stop.is_set():
            return None
        with self._lock:
            frame = self._pending
            self._pending = None
        return frame

    def _run_stream(self) -> None:
        """One held-open chunked upload: encode the newest frame, yield it as
        a packet, repeat. The whole live path is then stream in -> stream out
        with zero per-frame HTTP overhead."""
        if self._session is None:
            import requests

            self._session = requests.Session()

        def packets():
            while not self._stop.is_set():
                frame = self._next_frame()
                if frame is None:
                    continue
                t0 = time.monotonic()
                self._tick += 1
                jpeg = self._encode(frame)
                if jpeg:
                    stats = None
                    if self.stats_provider is not None:
                        try:
                            stats = self.stats_provider()
                        except Exception:
                            stats = None
                    yield frame_packet(jpeg, stats)
                # Pace to the target rate, counting the work already done.
                remaining = self._interval - (time.monotonic() - t0)
                if remaining > 0:
                    self._stop.wait(timeout=remaining)

        url = self.backend_url + LIVE_STREAM_ENDPOINT.format(camera_id=self.camera_id)
        headers = {"X-Camera-Id": self.camera_id,
                   "Content-Type": "application/octet-stream"}
        if self.api_token:
            headers["Authorization"] = f"Bearer {self.api_token}"
        logger.info("Live preview: streaming to %s", url)
        resp = self._session.post(url, data=packets(), headers=headers,
                                  timeout=self.timeout)
        # 404/405 = an older backend without the stream route: don't retry it.
        if resp.status_code in (404, 405):
            logger.info("Backend has no live-stream route (HTTP %s); using "
                        "per-frame POSTs.", resp.status_code)
            self.mode = "post"

    def _post_one(self) -> None:
        """Fallback mode: encode and POST a single frame."""
        frame = self._next_frame()
        if frame is None:
            return
        t0 = time.monotonic()
        self._tick += 1
        try:
            jpeg = self._encode(frame)
            if jpeg:
                self._send(jpeg)
        except Exception as exc:  # preview must never break the unit
            if not self._warned:
                logger.debug("Live preview push failed: %s", exc)
                self._warned = True
        # Pace to the target frame rate, COUNTING the encode+send time we
        # already spent (sleeping the full interval on top used to halve
        # the achieved rate).
        remaining = self._interval - (time.monotonic() - t0)
        if remaining > 0:
            self._stop.wait(timeout=remaining)

    # -- encoding ---------------------------------------------------------- #
    def _encode(self, frame: Any) -> Optional[bytes]:
        if not isinstance(frame, SyntheticFrame) and getattr(frame, "shape", None) is not None:
            return self._encode_real(frame)
        # Synthetic / mock: draw a stand-in live scene.
        from . import annotate

        w, h = frame_size(frame)
        out_w = min(self.max_width, w)
        out_h = max(1, int(out_w * h / max(w, 1)))
        return annotate.render_live_frame(out_w, out_h, camera_id=self.camera_id,
                                          tick=self._tick)

    def _encode_real(self, frame) -> Optional[bytes]:
        w, h = frame_size(frame)
        scale = min(1.0, self.max_width / max(w, 1))
        # Prefer OpenCV (already present where a real camera is), else Pillow.
        try:
            import cv2  # type: ignore

            img = frame
            resized = False
            if scale < 1.0:
                # INTER_AREA is both the fastest and cleanest way to shrink —
                # it averages source pixels instead of the default bilinear.
                img = cv2.resize(
                    frame,
                    (max(1, int(w * scale)), max(1, int(h * scale))),
                    interpolation=cv2.INTER_AREA,
                )
                resized = True
            if self.annotate and self.overlay_provider is not None:
                if not resized:
                    # Never draw on the shared frame the detector is reading.
                    img = frame.copy()
                img = self._draw_overlay(cv2, img, src_w=w, src_h=h)
            ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), self.jpeg_quality])
            if ok:
                return bytes(buf)
        except Exception:
            pass
        try:
            from PIL import Image

            im = Image.fromarray(frame[:, :, ::-1])  # BGR -> RGB
            if scale < 1.0:
                im = im.resize((max(1, int(w * scale)), max(1, int(h * scale))))
            out = io.BytesIO()
            im.save(out, format="JPEG", quality=self.jpeg_quality)
            return out.getvalue()
        except Exception:
            return None

    def _draw_overlay(self, cv2, img, *, src_w: int, src_h: int):
        """Burn the latest detection boxes into a preview frame.

        Boxes arrive in FULL-frame coordinates and are scaled to the (usually
        downscaled) preview. Detection runs slower than the preview, so the
        same boxes are drawn on a few consecutive frames — they visibly track
        the vehicles, just with the detector's slight lag.
        """
        try:
            overlay = self.overlay_provider()
        except Exception:
            return img
        if not overlay or not overlay.get("items"):
            return img
        if (time.monotonic() - overlay.get("ts", 0.0)) > _OVERLAY_MAX_AGE_SECONDS:
            return img
        ow, oh = overlay.get("frame_wh") or (src_w, src_h)
        ih, iw = img.shape[:2]
        sx, sy = iw / max(ow, 1), ih / max(oh, 1)
        font = cv2.FONT_HERSHEY_SIMPLEX
        for bbox, label, kind in overlay["items"]:
            try:
                color = _OVERLAY_COLORS.get(kind, (200, 200, 200))
                x1, y1 = int(bbox[0] * sx), int(bbox[1] * sy)
                x2, y2 = int(bbox[2] * sx), int(bbox[3] * sy)
                cv2.rectangle(img, (x1, y1), (x2, y2), color, 2)
                if not label:
                    continue
                (tw, th), base = cv2.getTextSize(label, font, 0.45, 1)
                # Label above the box, or inside the top edge if there's no room.
                ty = y1 - 6 if (y1 - th - 10) >= 0 else y1 + th + 8
                cv2.rectangle(img, (x1, ty - th - 4), (x1 + tw + 6, ty + base),
                              color, -1)
                cv2.putText(img, label, (x1 + 3, ty), font, 0.45,
                            (10, 10, 10), 1, cv2.LINE_AA)
            except Exception:
                continue  # one bad box must not kill the preview
        return img

    # -- sending ----------------------------------------------------------- #
    def _send(self, jpeg: bytes) -> None:
        if self._session is None:
            import requests

            self._session = requests.Session()

        url = self.backend_url + LIVE_ENDPOINT.format(camera_id=self.camera_id)
        headers = {"X-Camera-Id": self.camera_id, "Content-Type": "image/jpeg"}
        if self.api_token:
            headers["Authorization"] = f"Bearer {self.api_token}"
        if self.stats_provider is not None:
            try:
                stats = self.stats_provider()
                headers["X-Capture-FPS"] = str(stats.get("capture_fps", ""))
                headers["X-Detect-FPS"] = str(stats.get("detect_fps", ""))
                if stats.get("profile") is not None:
                    headers["X-ALPR-Profile"] = str(stats.get("profile"))
                if stats.get("source_fps") is not None:
                    headers["X-Source-FPS"] = str(stats.get("source_fps"))
                if stats.get("frame_width") is not None:
                    headers["X-Frame-Width"] = str(stats.get("frame_width"))
                if stats.get("frame_height") is not None:
                    headers["X-Frame-Height"] = str(stats.get("frame_height"))
                if stats.get("live_quality") is not None:
                    headers["X-Live-Quality"] = str(stats.get("live_quality"))
                if stats.get("cpu_temp_c") is not None:
                    headers["X-CPU-Temp-C"] = str(stats.get("cpu_temp_c"))
                if stats.get("queued") is not None:
                    headers["X-Queued-Events"] = str(stats.get("queued"))
            except Exception:
                pass
        self._session.post(url, data=jpeg, headers=headers, timeout=self.timeout)
