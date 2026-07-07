"""Typed configuration for an EisenFieder Surveillance camera unit.

Loading order (later wins):
    1. Built-in defaults (the dataclass defaults below).
    2. config.yaml (non-secret tunables).
    3. .env file + process environment, for secrets and per-machine overrides.

Environment overrides use the prefix ``EISENFIEDER_`` and ``__`` to descend into
nested sections, e.g.::

    EISENFIEDER_CAMERA__ID=EFS-SN-00231
    EISENFIEDER_SOURCE__BACKEND=usb
    EISENFIEDER_DETECTOR__BACKEND=mock

Relative file paths are resolved against the edge/ directory (where config.yaml
lives), so the app behaves the same no matter where you launch it from.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any, Optional

import yaml

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover - dotenv is a soft dependency
    load_dotenv = None  # type: ignore[assignment]

ENV_PREFIX = "EISENFIEDER_"


# --------------------------------------------------------------------------- #
# Section dataclasses
# --------------------------------------------------------------------------- #
@dataclass
class CameraIdentity:
    """Who this unit is (matches the serial you registered in the console)."""

    id: str = "EFS-DEV-0001"
    name: str = "Dev Laptop Simulator"
    location: str = "Front entrance"


@dataclass
class SourceConfig:
    """Where video frames come from."""

    backend: str = "auto"           # auto | synthetic | picamera2 | usb | rtsp | file
    # Pi 5 ALPR profiles: sharp_read | fast_lane | night_boost | pi_economy | custom.
    # A named profile moves capture resolution, FPS, live preview cost and ALPR
    # OCR budgets together. Use custom when hand-tuning every value.
    quality_profile: str = "sharp_read"
    usb_index: int = 0
    rtsp_url: str = ""
    file_path: str = "data/sample.mp4"
    loop_file: bool = True
    # Detection passes per second CAP (the loop is latest-frame-drop, so the
    # hardware is the real limit; a low cap starves the tracker of frames).
    process_fps: float = 10.0
    width: int = 1280
    height: int = 720
    # Webcam capture format + rate REQUESTED from the driver. MJPG matters a
    # lot: without it most webcams fall back to raw YUY2, which the USB bus
    # can only move at ~5-10 fps at 720p. Empty fourcc / 0 fps = leave the
    # driver's defaults alone.
    fourcc: str = "MJPG"
    fps: float = 30.0
    # Pi / UVC quality controls. Unsupported drivers ignore these best-effort.
    shutter_us: int = 0
    analogue_gain: float = 0.0
    denoise: str = ""
    auto_exposure: bool = True
    exposure: float = 0.0
    auto_focus: bool = True
    focus: float = 0.0
    buffer_count: int = 4


@dataclass
class DetectorConfig:
    """The AI stack. ``backend`` drives detection, plate reading and attributes.

    * ``mock``  — synthetic vehicles; no ML deps (laptop demo / CI).
    * ``yolo``  — real vehicle detection via ultralytics YOLO (needs PyTorch).
    * ``auto``  — try real, fall back to mock with a loud warning.
    """

    backend: str = "auto"
    model_path: str = "yolov8n.pt"
    confidence_threshold: float = 0.35
    device: str = "cpu"
    track: bool = True                  # track vehicles across frames (log once + direction)
    mock_interval_seconds: float = 3.0  # how often the mock "sees" a vehicle
    # Accuracy / speed tuning for the real YOLO backend:
    imgsz: int = 640                    # inference size; 480 = faster, 960 = more accurate on small/distant plates
    iou: float = 0.5                    # NMS IoU; lower = fewer overlapping dup boxes
    max_det: int = 20                   # cap detections per frame (an entrance won't have 300 cars)
    half: bool = False                  # FP16 — set true ONLY on CUDA, ~2x faster
    warmup: bool = True                 # run one dummy inference at startup so the FIRST real car isn't missed
    agnostic_nms: bool = False          # class-agnostic NMS (helps when truck/bus boxes overlap)
    # Tracker tuning file (ultralytics format). Empty = the bundled
    # trackers/efs_bytetrack.yaml (longer occlusion memory than the stock
    # config, so a car briefly hidden behind another keeps its track id).
    tracker_config: str = ""
    # CPU threads YOLO may use. 0 = auto: all cores MINUS TWO, so detection
    # can never starve the capture/live/upload threads (that starvation is
    # what made the live view stutter whenever the detector was busy).
    cpu_threads: int = 0

    # --- ALPR (license-plate reading) tuning ------------------------------- #
    # The plate is read on EVERY frame while a vehicle is tracked, and all the
    # reads are fused (character-level voting) when the vehicle leaves — far
    # more accurate than trusting any single frame.
    alpr_reads_per_track: int = 10       # budget: max OCR reads per vehicle pass
    alpr_min_vehicle_px: int = 56        # skip OCR while the vehicle box is tinier than this (px tall)
    alpr_retry_below_conf: float = 0.90  # below this, retry OCR on an enhanced (upscaled/contrast) crop
    alpr_min_read_conf: float = 0.50     # reads weaker than this are noise and discarded
    alpr_format_correction: bool = True  # repair O<->0 / I<->1 style mixups ONLY when a real
    #                                      plate layout confirms it (doubtful chars only)
    alpr_lock_after_agree: int = 3       # stop OCR for a vehicle once this many confident reads
    #                                      agree exactly (0 = keep reading; saves Pi CPU)
    alpr_skip_blur_below: float = 8.0    # skip OCR on frames blurrier than this (Laplacian
    #                                      variance of the downscaled vehicle crop; 0 = off)
    alpr_read_every_n: int = 2            # throttle OCR to every N detector frames per track
    stabilize_tracks: bool = True         # bridge YOLO/ByteTrack id churn with local IOU matching

    # --- Make/model classification (optional, OFF by default) ------------- #
    # A make/model classifier is only trustworthy once you've MEASURED it on
    # real entrance-cam crops (side/angle views, not clean catalog photos). So
    # it stays off until you (a) supply a model and (b) confirm its accuracy
    # with tools/measure_make_model.py. Until then make/model are left blank
    # rather than guessed — no fake data. See edge/MAKEMODEL.md.
    makemodel_backend: str = "off"          # off | onnx
    makemodel_model_path: str = ""          # path to the .onnx classifier
    makemodel_labels_path: str = ""         # text file, one label per line (order = class index)
    makemodel_min_confidence: float = 0.60  # below this, leave make/model blank
    makemodel_input_size: int = 224         # square input size the model expects


@dataclass
class EventsConfig:
    db_path: str = "data/events.db"
    image_dir: str = "data/events"
    annotate: bool = True
    # Don't log the same plate again within this many seconds (debounce a car
    # that lingers in frame). Falls back to a per-vehicle cooldown when no plate.
    # (Used by the mock path; the real tracker logs once per vehicle instead.)
    cooldown_seconds: float = 8.0
    # Direction is geometric and depends on how the camera is mounted: which way
    # a vehicle moving across the frame counts as "in". Set per install.
    direction_axis: str = "x"           # "x" (left/right) or "y" (up/down)
    direction_invert: bool = False      # flip if in/out come out backwards
    # A tracked vehicle must travel at least this fraction of the frame (or
    # clearly approach/leave head-on) before it becomes an event. Parked cars
    # never do — so they are never logged, no matter how often the tracker
    # re-detects them when something drives past.
    min_move_frac: float = 0.05
    provisional_events: bool = True


@dataclass
class UploaderConfig:
    enabled: bool = False
    backend_url: str = ""
    batch_size: int = 20
    poll_interval_seconds: float = 10.0
    request_timeout_seconds: float = 20.0
    max_attempts: int = 5
    # After an event uploads, delete its local stills so the SD card can't fill.
    delete_local_after_upload: bool = True
    # Live preview: push JPEG frames so the owner can watch the camera in the
    # console. Off by default (saves bandwidth); the demo turns it on. The
    # achieved rate is capped by the camera's capture rate (~30) and the LAN.
    live_enabled: bool = False
    live_fps: float = 20.0
    live_max_width: int = 720
    live_jpeg_quality: int = 70
    # Burn the detector's boxes (vehicles, people, plate text so far) into the
    # live preview so the owner can SEE what the AI sees, in real time.
    live_annotate: bool = True
    # "stream" = ONE held-open upload carrying every frame (fastest: no
    # per-frame HTTP overhead); "post" = one request per frame (fallback,
    # auto-selected if the backend doesn't support streaming).
    live_mode: str = "stream"


@dataclass
class Config:
    camera: CameraIdentity = field(default_factory=CameraIdentity)
    source: SourceConfig = field(default_factory=SourceConfig)
    detector: DetectorConfig = field(default_factory=DetectorConfig)
    events: EventsConfig = field(default_factory=EventsConfig)
    uploader: UploaderConfig = field(default_factory=UploaderConfig)
    log_level: str = "INFO"
    base_dir: Path = field(default_factory=Path.cwd)

    def resolve(self, path_str: str) -> Path:
        p = Path(path_str).expanduser()
        return p if p.is_absolute() else (self.base_dir / p)

    @property
    def db_path(self) -> Path:
        return self.resolve(self.events.db_path)

    @property
    def image_dir(self) -> Path:
        return self.resolve(self.events.image_dir)


# --------------------------------------------------------------------------- #
# Loading (defaults + yaml + env), identical mechanism to the predator unit
# --------------------------------------------------------------------------- #
def _coerce(value: str, current: Any) -> Any:
    """Coerce a string env value to match the *existing* value's type."""
    if isinstance(current, bool):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    if isinstance(current, int):
        try:
            return int(value)
        except ValueError:
            return value
    if isinstance(current, float):
        try:
            return float(value)
        except ValueError:
            return value
    if current is None:
        low = value.strip().lower()
        if low in {"true", "false"}:
            return low == "true"
        if low in {"none", "null", ""}:
            return None
        for caster in (int, float):
            try:
                return caster(value)
            except ValueError:
                continue
        return value
    return value


def _apply_dict(obj: Any, data: dict[str, Any]) -> None:
    if not is_dataclass(obj):
        return
    field_names = {f.name for f in fields(obj)}
    for key, value in data.items():
        if key not in field_names:
            continue
        current = getattr(obj, key)
        if is_dataclass(current) and isinstance(value, dict):
            _apply_dict(current, value)
        else:
            setattr(obj, key, value)


def _apply_env_overrides(obj: Any, prefix: str = ENV_PREFIX) -> None:
    if not is_dataclass(obj):
        return
    for f in fields(obj):
        if f.name == "base_dir":
            continue
        env_key = f"{prefix}{f.name.upper()}"
        current = getattr(obj, f.name)
        if is_dataclass(current):
            _apply_env_overrides(current, prefix=f"{env_key}__")
        elif env_key in os.environ:
            setattr(obj, f.name, _coerce(os.environ[env_key], current))


def load_config(config_path: Optional[str | os.PathLike] = None) -> Config:
    edge_dir = Path(__file__).resolve().parent.parent  # .../edge

    if config_path is None:
        config_path = edge_dir / "config.yaml"
    config_path = Path(config_path)

    if load_dotenv is not None:
        env_file = config_path.parent / ".env"
        load_dotenv(env_file if env_file.exists() else None)

    cfg = Config()
    cfg.base_dir = config_path.parent if config_path.parent.exists() else edge_dir

    if config_path.exists():
        with config_path.open("r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
        logging_section = raw.pop("logging", None)
        if isinstance(logging_section, dict) and "level" in logging_section:
            cfg.log_level = logging_section["level"]
        _apply_dict(cfg, raw)

    _apply_env_overrides(cfg)
    _apply_quality_profile(cfg)
    return cfg


def _apply_quality_profile(cfg: Config) -> None:
    """Apply a named Pi 5 ALPR capture profile after yaml/env overrides."""
    from .quality import profile_for

    profile = profile_for(cfg.source.quality_profile)
    if profile is None:
        return
    cfg.source.quality_profile = profile.id
    cfg.source.width = profile.width
    cfg.source.height = profile.height
    cfg.source.fps = profile.fps
    cfg.source.fourcc = profile.fourcc
    cfg.source.process_fps = profile.process_fps
    cfg.source.shutter_us = profile.shutter_us
    cfg.source.analogue_gain = profile.analogue_gain
    cfg.source.denoise = profile.denoise
    cfg.uploader.live_fps = profile.live_fps
    cfg.uploader.live_max_width = profile.live_max_width
    cfg.uploader.live_jpeg_quality = profile.live_jpeg_quality
    cfg.detector.alpr_reads_per_track = profile.alpr_reads_per_track
    cfg.detector.alpr_min_vehicle_px = profile.alpr_min_vehicle_px
    cfg.detector.alpr_skip_blur_below = profile.alpr_skip_blur_below
    cfg.detector.alpr_read_every_n = profile.alpr_read_every_n
