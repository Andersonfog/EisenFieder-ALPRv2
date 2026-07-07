"""Vehicle detector: a YOLO wrapper plus a dependency-free mock backend.

A :class:`VehicleDetection` is one vehicle found in a frame: its type, a
confidence score, and a bounding box. Plate reading and attribute recognition
happen *after* this step (see plate_reader.py / recognizer.py).

Backends:
    * :class:`YoloVehicleDetector` — ultralytics YOLO; keeps COCO vehicle classes.
    * :class:`MockVehicleDetector` — emits a synthetic vehicle on a timer, no ML
      deps, so the whole pipeline runs on a bare laptop.
"""

from __future__ import annotations

import itertools
import logging
import random
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .camera import frame_size

logger = logging.getLogger(__name__)

# Vehicle types we report. The YOLO/COCO stand-ins are in YOLO_VEHICLE_CLASSES.
VEHICLE_TYPES = ["car", "suv", "truck", "van", "pickup", "motorcycle", "bus"]

# COCO class name -> our vehicle type (real weights make this finer-grained).
YOLO_VEHICLE_CLASSES = {
    "car": "car",
    "truck": "truck",
    "bus": "bus",
    "motorcycle": "motorcycle",
}


@dataclass
class VehicleDetection:
    vehicle_type: str
    confidence: float
    bbox: tuple[int, int, int, int]   # (x1, y1, x2, y2) in pixels
    track_id: Optional[int] = None    # stable id across frames when tracking is on
    occupant_count: Optional[int] = None  # people seen inside this vehicle (real backend)

    def __str__(self) -> str:
        x1, y1, x2, y2 = self.bbox
        tid = "" if self.track_id is None else f" #{self.track_id}"
        return f"{self.vehicle_type}{tid} {self.confidence:.2f} @ [{x1},{y1},{x2},{y2}]"


class BaseDetector(ABC):
    name: str = "base"
    # Whether this backend also reports person boxes (for occupant counting).
    supports_persons: bool = False
    # Person boxes found in the most recent frame (empty unless supports_persons).
    last_person_boxes: list[tuple[int, int, int, int]] = []

    @abstractmethod
    def detect(self, frame) -> list[VehicleDetection]:
        """Return vehicle detections in a single frame."""


# --------------------------------------------------------------------------- #
# Real YOLO backend
# --------------------------------------------------------------------------- #
class YoloVehicleDetector(BaseDetector):  # pragma: no cover - needs torch/weights
    name = "yolo"
    supports_persons = True

    def __init__(self, det_cfg) -> None:
        from ultralytics import YOLO  # heavy import, deferred until used

        self._cfg = det_cfg
        self._track = bool(getattr(det_cfg, "track", True))
        self.last_person_boxes: list[tuple[int, int, int, int]] = []

        # On CPU, cap torch's thread pool BELOW the core count. By default it
        # grabs every core, which starves the capture/live/upload threads and
        # makes the live view stutter whenever the detector is working.
        if str(det_cfg.device or "cpu").lower().startswith("cpu"):
            try:
                import os

                import torch
                threads = int(getattr(det_cfg, "cpu_threads", 0))
                if threads <= 0:
                    cores = os.cpu_count() or 4
                    threads = max(1, min(6, cores - 1))
                torch.set_num_threads(threads)
                logger.info("YOLO CPU threads capped at %d (leaves cores free "
                            "for capture/live/upload)", threads)
            except Exception as exc:
                logger.debug("Could not cap torch threads: %s", exc)

        logger.info("Loading YOLO model: %s (device=%s, tracking=%s)",
                    det_cfg.model_path, det_cfg.device, self._track)
        self._model = YOLO(det_cfg.model_path)
        self._names: dict[int, str] = dict(self._model.names)

        # Restrict inference to vehicle COCO classes + person (for occupant
        # counting). Passing class ids to YOLO filters INSIDE the model (cheaper
        # NMS, no sign/other boxes to discard) instead of afterwards.
        wanted = set(YOLO_VEHICLE_CLASSES) | {"person"}
        self._class_ids = [i for i, n in self._names.items() if n in wanted] or None

        # Shared predict/track kwargs (read once, not per frame).
        self._imgsz = int(getattr(det_cfg, "imgsz", 640))
        self._iou = float(getattr(det_cfg, "iou", 0.5))
        self._max_det = int(getattr(det_cfg, "max_det", 20))
        self._half = bool(getattr(det_cfg, "half", False))
        self._agnostic = bool(getattr(det_cfg, "agnostic_nms", False))

        # Tracker tuning: an explicit file wins, else the bundled config with
        # longer occlusion memory, else ultralytics' stock bytetrack.yaml.
        tracker_cfg = str(getattr(det_cfg, "tracker_config", "") or "").strip()
        if not tracker_cfg:
            bundled = Path(__file__).resolve().parent / "trackers" / "efs_bytetrack.yaml"
            tracker_cfg = str(bundled) if bundled.exists() else "bytetrack.yaml"
        self._tracker_cfg = tracker_cfg
        if self._track:
            logger.info("Tracker config: %s", self._tracker_cfg)

        # Warm up: the very first inference loads CUDA/JIT kernels and is much
        # slower — without this the first car to arrive can sail past unseen.
        if getattr(det_cfg, "warmup", True):
            try:
                import numpy as np
                blank = np.zeros((self._imgsz, self._imgsz, 3), dtype="uint8")
                self._model.predict(blank, imgsz=self._imgsz, device=det_cfg.device,
                                    verbose=False)
                logger.info("YOLO warm-up complete.")
            except Exception as exc:
                logger.debug("YOLO warm-up skipped: %s", exc)

    def detect(self, frame) -> list[VehicleDetection]:
        common = dict(
            conf=self._cfg.confidence_threshold, device=self._cfg.device,
            classes=self._class_ids, imgsz=self._imgsz, iou=self._iou,
            max_det=self._max_det, half=self._half, agnostic_nms=self._agnostic,
            verbose=False,
        )
        # track() keeps stable ids across frames (so each vehicle logs once and
        # we can tell entering from leaving); predict() is a stateless fallback.
        if self._track:
            results = self._model.track(
                frame, persist=True, tracker=self._tracker_cfg, **common,
            )
        else:
            results = self._model.predict(frame, **common)
        out: list[VehicleDetection] = []
        persons: list[tuple[int, int, int, int]] = []
        for result in results:
            boxes = getattr(result, "boxes", None)
            if boxes is None:
                continue
            for box in boxes:
                source = self._names.get(int(box.cls[0]), "")
                x1, y1, x2, y2 = (int(v) for v in box.xyxy[0].tolist())
                if source == "person":
                    persons.append((x1, y1, x2, y2))
                    continue
                vtype = YOLO_VEHICLE_CLASSES.get(source)
                if vtype is None:
                    continue  # not a vehicle class
                track_id = None
                if getattr(box, "id", None) is not None:
                    track_id = int(box.id[0])
                out.append(VehicleDetection(vtype, float(box.conf[0]), (x1, y1, x2, y2),
                                            track_id=track_id))
        self.last_person_boxes = persons
        return out


# --------------------------------------------------------------------------- #
# Mock backend (no ML deps) — for the laptop demo & tests
# --------------------------------------------------------------------------- #
class MockVehicleDetector(BaseDetector):
    name = "mock"

    def __init__(self, interval_seconds: float = 3.0) -> None:
        self._interval = interval_seconds
        self._cycle = itertools.cycle(VEHICLE_TYPES)
        self._last_emit = 0.0
        logger.warning(
            "Detector: using MOCK backend (no real inference) - a synthetic "
            "vehicle every %.1fs.", interval_seconds,
        )

    def detect(self, frame) -> list[VehicleDetection]:
        now = time.monotonic()
        if now - self._last_emit < self._interval:
            return []
        self._last_emit = now

        w, h = frame_size(frame)
        x1, y1, x2, y2 = int(w * 0.30), int(h * 0.35), int(w * 0.70), int(h * 0.75)
        return [VehicleDetection(
            vehicle_type=next(self._cycle),
            confidence=round(random.uniform(0.78, 0.97), 2),
            bbox=(x1, y1, x2, y2),
        )]


def create_detector(det_cfg) -> BaseDetector:
    backend = (det_cfg.backend or "auto").lower()
    if backend == "mock":
        return MockVehicleDetector(det_cfg.mock_interval_seconds)
    if backend == "yolo":
        return YoloVehicleDetector(det_cfg)
    try:
        return YoloVehicleDetector(det_cfg)
    except Exception as exc:
        logger.warning(
            "YOLO backend unavailable (%s); falling back to mock detector.", exc
        )
        return MockVehicleDetector(det_cfg.mock_interval_seconds)
