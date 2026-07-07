"""Camera abstraction with automatic fallback.

A single :class:`FrameSource` interface is implemented by several backends:

    * :class:`PiCameraSource`  — Raspberry Pi camera via picamera2 (guarded import).
    * :class:`OpenCVSource`    — USB webcam, RTSP stream, or video file via OpenCV.
    * :class:`SyntheticSource` — generates blank frames with NO dependencies, so
      the pipeline runs on a laptop with no camera and no OpenCV. Used for the
      mock demo.

:func:`create_camera` picks a backend from config. In ``auto`` mode it tries the
Pi camera, then a USB webcam, then a video file, then the synthetic source — so
the exact same code runs on a field unit and on a bare laptop.

A frame is intentionally typed ``Any``: OpenCV/Pi yield numpy arrays; the
synthetic source yields a tiny :class:`SyntheticFrame`. Use :func:`frame_size`
to read dimensions without caring which it is.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger(__name__)


class CameraUnavailable(RuntimeError):
    """Raised when no camera backend could be initialised."""


@dataclass
class SyntheticFrame:
    """A frame stand-in for the mock pipeline (no pixels needed)."""

    width: int = 1280
    height: int = 720


def frame_size(frame: Any) -> tuple[int, int]:
    """Return (width, height) for a numpy array or a SyntheticFrame."""
    if isinstance(frame, SyntheticFrame):
        return frame.width, frame.height
    shape = getattr(frame, "shape", None)
    if shape and len(shape) >= 2:
        return int(shape[1]), int(shape[0])  # numpy is (h, w, c)
    return 1280, 720


class FrameSource(ABC):
    name: str = "unknown"

    @abstractmethod
    def read(self) -> Optional[Any]:
        """Return the next frame, or ``None`` if one isn't available right now."""

    def release(self) -> None:  # pragma: no cover - trivial default
        """Release any underlying hardware/file handles."""


# --------------------------------------------------------------------------- #
# Synthetic source (no dependencies) — the laptop/mock default
# --------------------------------------------------------------------------- #
class SyntheticSource(FrameSource):
    name = "synthetic"

    def __init__(self, width: int = 1280, height: int = 720) -> None:
        self._frame = SyntheticFrame(width, height)
        logger.warning(
            "Camera: using SYNTHETIC source (no real video) - blank %dx%d frames.",
            width, height,
        )

    def read(self) -> Optional[Any]:
        return self._frame


# --------------------------------------------------------------------------- #
# OpenCV-based source: USB webcam, RTSP, or video file
# --------------------------------------------------------------------------- #
class OpenCVSource(FrameSource):
    def __init__(self, target, *, name: str, width: int = 0, height: int = 0,
                 loop_file: bool = False, is_file: bool = False,
                 fourcc: str = "", fps: float = 0.0, api: str = "",
                 probe: bool = False) -> None:
        import cv2  # local import keeps OpenCV optional until a real camera is used

        self._cv2 = cv2
        self.name = name
        self._loop_file = loop_file
        self._is_file = is_file
        api_pref = {"dshow": getattr(cv2, "CAP_DSHOW", None),
                    "msmf": getattr(cv2, "CAP_MSMF", None)}.get(api)
        self._cap = (cv2.VideoCapture(target, api_pref) if api_pref is not None
                     else cv2.VideoCapture(target))
        if not self._cap.isOpened():
            raise CameraUnavailable(f"OpenCV could not open source: {target!r}")
        if not is_file:
            # ORDER MATTERS on many drivers: pixel format first, then size,
            # then rate. Without MJPG most webcams fall back to raw YUY2,
            # which the USB bus can only carry at ~5-10 fps at 720p — that
            # single setting is usually the difference between a slideshow
            # and a real 30 fps feed. All best-effort: a driver that ignores
            # a property just keeps its default.
            try:
                if fourcc and len(fourcc) == 4:
                    self._cap.set(cv2.CAP_PROP_FOURCC,
                                  cv2.VideoWriter_fourcc(*fourcc.upper()))
                if width:
                    self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
                if height:
                    self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
                if fps:
                    self._cap.set(cv2.CAP_PROP_FPS, float(fps))
                # Keep at most one frame queued: the pipeline always wants the
                # NEWEST frame, and a deep driver buffer adds a lag you can see.
                self._cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            except Exception as exc:
                logger.debug("Camera property setup partially failed: %s", exc)
            if probe:
                ok, _ = self._cap.read()
                if not ok:
                    self._cap.release()
                    raise CameraUnavailable(
                        f"{name} opened but could not deliver a frame")
            got_w = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
            got_h = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
            got_fps = float(self._cap.get(cv2.CAP_PROP_FPS) or 0)
            logger.info("Camera negotiated %dx%d @ %.0f fps (%s)",
                        got_w, got_h, got_fps, name)

    def read(self) -> Optional[Any]:
        ok, frame = self._cap.read()
        if ok and frame is not None:
            return frame
        if self._is_file and self._loop_file:
            self._cap.set(self._cv2.CAP_PROP_POS_FRAMES, 0)
            ok, frame = self._cap.read()
            if ok and frame is not None:
                return frame
        return None

    def release(self) -> None:
        try:
            self._cap.release()
        except Exception:  # pragma: no cover - defensive
            pass


# --------------------------------------------------------------------------- #
# Raspberry Pi camera source (picamera2)
# --------------------------------------------------------------------------- #
class PiCameraSource(FrameSource):  # pragma: no cover - hardware path
    name = "picamera2"

    def __init__(self, cfg) -> None:
        from picamera2 import Picamera2  # guarded: only present on a Pi

        self._picam = Picamera2()
        controls = {}
        fps = float(getattr(cfg, "fps", 0.0) or 0.0)
        shutter = int(getattr(cfg, "shutter_us", 0) or 0)
        gain = float(getattr(cfg, "analogue_gain", 0.0) or 0.0)
        if fps > 0:
            frame_us = int(1_000_000 / fps)
            controls["FrameDurationLimits"] = (frame_us, frame_us)
        if shutter > 0:
            controls["AeEnable"] = False
            controls["ExposureTime"] = shutter
        if gain > 0:
            controls["AnalogueGain"] = gain
        kwargs = {
            "main": {"size": (cfg.width, cfg.height), "format": "RGB888"},
            "controls": controls or None,
            "buffer_count": max(2, int(getattr(cfg, "buffer_count", 4) or 4)),
        }
        try:
            config = self._picam.create_video_configuration(**kwargs)
        except TypeError:
            config = self._picam.create_video_configuration(
                main={"size": (cfg.width, cfg.height), "format": "RGB888"}
            )
        self._picam.configure(config)
        self._picam.start()
        denoise = str(getattr(cfg, "denoise", "") or "")
        if denoise:
            try:
                self._picam.set_controls({"NoiseReductionMode": denoise})
            except Exception:
                pass

    def read(self) -> Optional[Any]:
        try:
            import cv2

            frame = self._picam.capture_array()
            return cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        except Exception as exc:
            logger.warning("picamera2 read failed: %s", exc)
            return None

    def release(self) -> None:
        try:
            self._picam.stop()
        except Exception:
            pass


# --------------------------------------------------------------------------- #
# Factory
# --------------------------------------------------------------------------- #
def _try_picamera(cfg) -> Optional[FrameSource]:
    try:
        src = PiCameraSource(cfg)
        logger.info(
            "Camera: using Raspberry Pi camera (picamera2) %dx%d @ %.0f fps profile=%s",
            cfg.width,
            cfg.height,
            getattr(cfg, "fps", 0.0) or 0.0,
            getattr(cfg, "quality_profile", "custom"),
        )
        return src
    except Exception as exc:
        logger.debug("picamera2 unavailable: %s", exc)
        return None


def _try_usb(cfg) -> Optional[FrameSource]:
    import sys

    # On Windows, DirectShow honors the format/fps requests far more reliably
    # than the default MSMF backend; fall back if it can't deliver frames.
    apis = ["dshow", ""] if sys.platform == "win32" else [""]
    last_exc: Optional[Exception] = None
    for api in apis:
        try:
            src = OpenCVSource(
                cfg.usb_index, name=f"usb:{cfg.usb_index}",
                width=cfg.width, height=cfg.height,
                fourcc=getattr(cfg, "fourcc", ""), fps=getattr(cfg, "fps", 0.0),
                api=api, probe=True,
            )
            logger.info("Camera: using USB webcam at index %s%s", cfg.usb_index,
                        f" via {api}" if api else "")
            return src
        except Exception as exc:
            last_exc = exc
    logger.debug("USB webcam unavailable: %s", last_exc)
    return None


def _try_file(cfg, base_dir) -> Optional[FrameSource]:
    if not cfg.file_path:
        return None
    from pathlib import Path

    path = Path(cfg.file_path)
    if not path.is_absolute() and base_dir is not None:
        path = base_dir / path
    if not path.exists():
        return None
    try:
        src = OpenCVSource(str(path), name=f"file:{path.name}",
                           loop_file=cfg.loop_file, is_file=True)
        logger.info("Camera: using video file %s (loop=%s)", path, cfg.loop_file)
        return src
    except Exception as exc:
        logger.debug("Video file unavailable: %s", exc)
        return None


def create_camera(cfg, base_dir=None) -> FrameSource:
    """Build a :class:`FrameSource` from the source config (with auto-fallback)."""
    backend = (cfg.backend or "auto").lower()

    if backend == "synthetic":
        return SyntheticSource(cfg.width, cfg.height)
    if backend == "picamera2":
        src = _try_picamera(cfg)
        if src:
            return src
        raise CameraUnavailable("picamera2 requested but unavailable")
    if backend == "usb":
        src = _try_usb(cfg)
        if src:
            return src
        raise CameraUnavailable(f"USB webcam {cfg.usb_index} requested but unavailable")
    if backend == "rtsp":
        if not cfg.rtsp_url:
            raise CameraUnavailable("rtsp source requested but rtsp_url is empty")
        return OpenCVSource(cfg.rtsp_url, name="rtsp")
    if backend == "file":
        src = _try_file(cfg, base_dir)
        if src:
            return src
        raise CameraUnavailable(f"video file requested but unavailable: {cfg.file_path}")

    # auto: Pi camera -> USB -> file -> synthetic (synthetic always works).
    for attempt in (_try_picamera(cfg), _try_usb(cfg), _try_file(cfg, base_dir)):
        if attempt:
            return attempt
    logger.info("Camera: auto found no real source; using synthetic frames.")
    return SyntheticSource(cfg.width, cfg.height)
