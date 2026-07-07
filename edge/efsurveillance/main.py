"""EisenFieder Surveillance edge main loop.

    capture a frame  ->  detect vehicles  ->  for each vehicle:
      read the plate  ->  recognize attributes (make/color/occupants/company)  ->
      debounce by plate  ->  save stills  ->  log the event to SQLite

A background uploader drains the local buffer to the backend (store-and-forward).

Robustness is the priority: a camera hiccup, a model error, or end-of-video must
never take the unit down. Failures are logged, backed off, and recovered from.
"""

from __future__ import annotations

import argparse
import base64
import logging
import os
import random
import signal
import threading
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from . import annotate
from .camera import CameraUnavailable, FrameSource, create_camera, frame_size
from .camera_config import CameraConfigClient
from .config import Config, load_config
from .detector import BaseDetector, VehicleDetection, create_detector
from .event_logger import EventLogger
from .live import LivePusher
from .plate_fusion import best_crop_observation, fuse_observations
from .plate_reader import PlateResult, create_plate_reader, quick_sharpness
from .recognizer import create_recognizer
from .tracking import TrackManager, TrackStabilizer
from .uploader import Uploader

logger = logging.getLogger("efsurveillance")

_MAX_CONSECUTIVE_READ_FAILURES = 30
# Cap frame capture so an instant source (synthetic) doesn't busy-spin the CPU.
# A real webcam blocks in read() at its own frame rate, so this only needs to
# sit ABOVE the hardware rate — the camera itself is the pace-setter.
_CAPTURE_FPS_CAP = 90.0

# A tiny valid 1x1 JPEG, used as the saved still when there's no real frame
# (synthetic/mock mode). On the Pi with OpenCV, a real frame is saved instead.
_PLACEHOLDER_JPEG = base64.b64decode(
    "/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRof"
    "Hh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/wAALCAABAAEBAREA/8QAFAAB"
    "AAAAAAAAAAAAAAAAAAAAAv/EABQQAQAAAAAAAAAAAAAAAAAAAAD/xAAUAQEAAAAAAAAAAAAA"
    "AAAAAAAA/8QAFBEBAAAAAAAAAAAAAAAAAAAAAP/aAAwDAQACEQMRAD8Af//Z"
)


def setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, str(level).upper(), logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def _write_bytes(path: Path, data: bytes) -> Optional[str]:
    """Write already-encoded JPEG bytes to disk. Returns the path or None."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return str(path)
    except Exception as exc:  # pragma: no cover - disk issues
        logger.warning("Failed to save still %s: %s", path, exc)
        return None


def _pi_cpu_temp_c() -> Optional[float]:
    path = "/sys/class/thermal/thermal_zone0/temp"
    try:
        if os.path.exists(path):
            return round(float(Path(path).read_text().strip()) / 1000.0, 1)
    except Exception:
        return None
    return None


def _box_iou(a: tuple, b: tuple) -> float:
    ax1, ay1, ax2, ay2 = (float(v) for v in a)
    bx1, by1, bx2, by2 = (float(v) for v in b)
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    denom = area_a + area_b - inter
    return inter / denom if denom > 0 else 0.0


class _FpsCounter:
    """Rolling frames-per-second over the last N ticks."""

    def __init__(self, window: int = 30) -> None:
        self._t: deque[float] = deque(maxlen=window)

    def tick(self) -> None:
        self._t.append(time.monotonic())

    def fps(self) -> float:
        if len(self._t) < 2:
            return 0.0
        span = self._t[-1] - self._t[0]
        return (len(self._t) - 1) / span if span > 0 else 0.0


class SurveillanceApp:
    def __init__(self, config: Config) -> None:
        self.cfg = config
        self.camera: Optional[FrameSource] = None
        self.detector: Optional[BaseDetector] = None
        self.plate_reader = None
        self.recognizer = None
        self.events: Optional[EventLogger] = None
        self.uploader: Optional[Uploader] = None
        self.tracker: Optional[TrackManager] = None
        self.track_stabilizer: Optional[TrackStabilizer] = None
        self.live: Optional[LivePusher] = None
        self.camera_config: Optional[CameraConfigClient] = None
        self._running = False
        self._last_seen: dict[str, float] = {}     # plate/key -> monotonic ts
        self._frames = 0
        self._detections = 0
        self._logged = 0
        self._cap_fps = _FpsCounter()    # camera capture rate
        self._det_fps = _FpsCounter()    # detector (YOLO) rate
        self._det_seq = 0                # detection-cycle counter (not camera frames)
        self._last_plate_read_seq: dict[int, int] = {}
        # Latest captured frame, shared from the capture thread to the detector.
        self._latest_frame = None
        self._frame_seq = 0
        self._frame_lock = threading.Lock()
        # What the detector saw most recently, for the live-view overlay
        # (written by the detect loop, read by the live-push thread).
        self._overlay: Optional[dict] = None
        # Set by the capture thread when a fresh frame lands, so the detect
        # loop sleeps until there is work instead of polling on a timer.
        self._frame_ready = threading.Event()
        self._capture_thread: Optional[threading.Thread] = None

    # -- setup ------------------------------------------------------------- #
    def setup(self) -> None:
        cfg = self.cfg
        logger.info("=" * 64)
        logger.info("EisenFieder Surveillance camera starting")
        logger.info("Camera   : %s (%s) @ %s", cfg.camera.id, cfg.camera.name, cfg.camera.location)
        logger.info("Source   : backend=%s", cfg.source.backend)
        logger.info("Detector : backend=%s  conf>=%.2f", cfg.detector.backend,
                    cfg.detector.confidence_threshold)
        logger.info("=" * 64)

        self.events = EventLogger(cfg.db_path)
        self.detector = create_detector(cfg.detector)
        self.plate_reader = create_plate_reader(cfg.detector.backend, cfg.detector)
        self.recognizer = create_recognizer(cfg.detector.backend, cfg.detector)
        self.tracker = TrackManager(
            axis=cfg.events.direction_axis, invert=cfg.events.direction_invert,
            miss_grace=75, min_frames=4,
            min_move_frac=cfg.events.min_move_frac)
        if getattr(cfg.detector, "stabilize_tracks", True):
            self.track_stabilizer = TrackStabilizer()
        self.uploader = Uploader(cfg.uploader, self.events, camera_id=cfg.camera.id)
        self.uploader.start()
        self.live = LivePusher(
            cfg.uploader, camera_id=cfg.camera.id,
            backend_url=self.uploader.backend_url, api_token=self.uploader.api_token,
            stats_provider=self._live_stats, overlay_provider=self._live_overlay,
        )
        self.live.start()
        self.camera_config = CameraConfigClient(
            backend_url=self.uploader.backend_url,
            camera_id=cfg.camera.id,
            api_token=self.uploader.api_token,
        )
        self.camera_config.start()
        self.camera = create_camera(cfg.source, base_dir=cfg.base_dir)

    def _settings(self) -> dict:
        if self.camera_config is not None:
            return self.camera_config.get()
        return {
            "excluded_types": [], "min_confidence": None, "capture_plate": True,
            "capture_occupants": True, "capture_company": True, "alerts_enabled": True,
        }

    @property
    def _mock_mode(self) -> bool:
        return bool(self.detector and self.detector.name == "mock")

    def _live_stats(self) -> dict:
        """Current pipeline rates, attached to live frames for the FPS meter."""
        with self._frame_lock:
            frame = self._latest_frame
        width, height = frame_size(frame) if frame is not None else (
            self.cfg.source.width, self.cfg.source.height)
        return {
            "capture_fps": round(self._cap_fps.fps(), 1),
            "detect_fps": round(self._det_fps.fps(), 1),
            "profile": self.cfg.source.quality_profile,
            "source_fps": round(float(self.cfg.source.fps or 0), 1),
            "frame_width": width,
            "frame_height": height,
            "live_quality": self.cfg.uploader.live_jpeg_quality,
            "cpu_temp_c": _pi_cpu_temp_c(),
            "queued": self.events.count_unsynced() if self.events else None,
        }

    def _live_overlay(self) -> Optional[dict]:
        """Newest detection boxes for the live-view overlay (see LivePusher)."""
        return self._overlay

    def _publish_overlay(self, frame, detections) -> None:
        """Share what the detector just saw with the live preview: one box per
        vehicle (with the best plate read so far) and one per person."""
        items = []
        if self.track_stabilizer is not None and not self._mock_mode:
            items.extend(self.track_stabilizer.overlay_items(
                self._det_seq, frame_size(frame)))
        else:
            for det in detections:
                label = f"{det.vehicle_type.upper()} {int(det.confidence * 100)}%"
                if det.track_id is not None and self.tracker is not None:
                    plate = self.tracker.latest_plate_text(det.track_id)
                    if plate:
                        # ASCII only: cv2's built-in font can't draw fancy glyphs.
                        label = f"{label} - {plate}"
                items.append((det.bbox, label, "vehicle"))
        for pbox in getattr(self.detector, "last_person_boxes", []) or []:
            items.append((pbox, "PERSON", "person"))
        self._overlay = {"ts": time.monotonic(),
                         "frame_wh": frame_size(frame), "items": items}

    # -- per-vehicle handling --------------------------------------------- #
    def _passes_filters(self, det: VehicleDetection, settings: dict) -> bool:
        """Per-camera excluded types + confidence override."""
        if det.vehicle_type in (settings.get("excluded_types") or []):
            return False
        min_conf = settings.get("min_confidence")
        if min_conf is not None and det.confidence < min_conf:
            return False
        return True

    def _read_plate(self, frame, bbox, settings):
        if settings.get("capture_plate", True) and self.plate_reader is not None:
            return self.plate_reader.read(frame, bbox)
        return None

    def _annotate_occupants(self, detections, settings: dict) -> None:
        """Count people inside each vehicle box (real, person-aware backend only).

        Left as None for the mock backend (no real people), so the mock demo
        keeps using the recognizer's stand-in occupant value.
        """
        if not (self.detector and self.detector.supports_persons):
            return
        if not settings.get("capture_occupants", True):
            return
        from .occupancy import count_occupants
        persons = getattr(self.detector, "last_person_boxes", []) or []
        for det in detections:
            det.occupant_count = count_occupants(det.bbox, persons)

    def _dedupe_detections(self, detections: list[VehicleDetection]) -> list[VehicleDetection]:
        """Drop duplicate vehicle boxes before they split into separate tracks."""
        if len(detections) <= 1:
            return detections
        kept: list[VehicleDetection] = []
        for det in sorted(detections, key=lambda d: d.confidence, reverse=True):
            duplicate = False
            for prev in kept:
                if _box_iou(det.bbox, prev.bbox) >= 0.45:
                    duplicate = True
                    break
            if not duplicate:
                kept.append(det)
        return kept

    def _vehicle_profile(self, ft) -> tuple[Optional[bytes], Optional[list]]:
        """The best SIDE-view crop of a finished pass (as JPEG bytes) plus its
        appearance fingerprint. Real frames only — never synthesized, and an
        unusable crop honestly returns (None, None)."""
        frame = ft.profile_frame if ft.profile_frame is not None else ft.frame
        bbox = ft.profile_bbox if ft.profile_bbox is not None else ft.bbox
        if getattr(frame, "shape", None) is None or bbox is None:
            return None, None
        try:
            import cv2

            from .profiles import compute_fingerprint

            h, w = frame.shape[:2]
            x1, y1, x2, y2 = (int(v) for v in bbox)
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(w, x2), min(h, y2)
            if x2 <= x1 or y2 <= y1:
                return None, None
            crop = frame[y1:y2, x1:x2]
            vec = compute_fingerprint(crop)
            ok, buf = cv2.imencode(".jpg", crop,
                                   [int(cv2.IMWRITE_JPEG_QUALITY), 88])
            return (buf.tobytes() if ok else None), vec
        except Exception as exc:
            logger.debug("Vehicle profile capture failed: %s", exc)
            return None, None

    def _commit(self, frame, *, bbox, vehicle_type, confidence, plate, attrs, direction,
                settings, occupant_count=None, plate_still: Optional[bytes] = None,
                event_uuid: Optional[str] = None, pending: bool = False,
                profile_still: Optional[bytes] = None,
                extra_meta: Optional[dict] = None) -> None:
        """Shared tail: save the annotated stills and log one vehicle event.

        ``event_uuid`` ties an instant provisional event ("vehicle in view",
        ``pending=True``) to its final enriched commit — same id, one log row
        that updates in place instead of a duplicate."""
        cfg = self.cfg
        # A real person-count (from the detector) wins; else the recognizer's
        # value (the mock backend's stand-in). May be None = not captured.
        occ = occupant_count if occupant_count is not None else attrs.occupant_count
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%f")
        base = f"{cfg.camera.id}_{ts}"
        plate_text = plate.text if plate and plate.text else None
        # Prefer the real plate box from the ALPR. Only the mock/synthetic demo
        # gets an estimated stand-in box — a real photo never gets a fake box.
        is_real_frame = getattr(frame, "shape", None) is not None
        plate_box = (plate.bbox if plate and plate.bbox
                     else (annotate.synth_plate_bbox(bbox)
                           if plate_text and not is_real_frame else None))
        make_model = " ".join(p for p in [attrs.make, attrs.model] if p)
        label = " ".join(p for p in [(attrs.color or "").title(), make_model] if p) \
            or vehicle_type
        label = f"{label}  ·  {vehicle_type.upper()} {direction.upper()}"

        image_path = _write_bytes(
            cfg.image_dir / f"{base}.jpg",
            annotate.render_event_image(
                frame, vehicle_bbox=bbox, plate_bbox=plate_box,
                vehicle_label=label, plate_label=plate_text, vehicle_color=attrs.color,
            ),
        )
        # Plate close-up: a pre-rendered best-shot (sharpest crop across the
        # whole pass) wins; else crop from this frame when we have a real box.
        plate_image_path = None
        if plate_still is not None:
            plate_image_path = _write_bytes(cfg.image_dir / f"{base}_plate.jpg", plate_still)
        elif plate_text and (plate_box is not None or not is_real_frame):
            plate_image_path = _write_bytes(
                cfg.image_dir / f"{base}_plate.jpg",
                annotate.render_plate_crop(frame, plate_box, plate_text,
                                           plate.region if plate else None),
            )

        # Side-profile photo of the pass (real pixels; the appearance
        # fingerprint travels in the event metadata).
        profile_image_path = None
        if profile_still is not None:
            profile_image_path = _write_bytes(
                cfg.image_dir / f"{base}_side.jpg", profile_still)

        meta: dict = {"detector": self.detector.name if self.detector else "?"}
        if extra_meta:
            meta.update(extra_meta)

        assert self.events is not None
        self.events.log_vehicle(
            camera_id=cfg.camera.id,
            captured_at=datetime.now(timezone.utc).isoformat(),
            direction=direction,
            plate_text=plate.text if plate else None,
            plate_confidence=plate.confidence if plate else None,
            plate_region=plate.region if plate else None,
            vehicle_type=vehicle_type,
            vehicle_make=attrs.make,
            vehicle_model=attrs.model,
            vehicle_color=attrs.color,
            occupant_count=occ,
            is_commercial=attrs.is_commercial,
            company_name=attrs.company_name,
            confidence=confidence,
            image_path=image_path,
            plate_image_path=plate_image_path,
            profile_image_path=profile_image_path,
            metadata=meta,
            event_uuid=event_uuid,
            pending=pending,
        )
        if not pending:
            self._logged += 1
        # New event on the books → push it to the console NOW, not next poll.
        if self.uploader is not None:
            try:
                self.uploader.kick()
            except Exception:
                pass
        logger.info(
            "*** VEHICLE%s *** %s %s plate=%s %s%s",
            " (in view)" if pending else "",
            f"{attrs.color or '?'} {make_model}".strip(), vehicle_type,
            (plate_text or "—"), direction,
            f"  [{attrs.company_name}]" if attrs.company_name else "",
        )

    def _handle_detection(self, frame, det: VehicleDetection) -> None:
        """Untracked path (mock detector): filter, read plate, debounce, log."""
        settings = self._settings()
        if not self._passes_filters(det, settings):
            return
        plate = self._read_plate(frame, det.bbox, settings)

        # Debounce: keyed by plate, else a coarse position+type cell.
        if plate and plate.text:
            key = plate.text
        else:
            cx = (det.bbox[0] + det.bbox[2]) // 2
            cy = (det.bbox[1] + det.bbox[3]) // 2
            key = f"{det.vehicle_type}:{cx // 140}:{cy // 140}"
        now = time.monotonic()
        last = self._last_seen.get(key)
        if last is not None and (now - last) < self.cfg.events.cooldown_seconds:
            return
        self._last_seen[key] = now

        attrs = self.recognizer.recognize(
            frame, det.bbox,
            occupants=settings.get("capture_occupants", True),
            company=settings.get("capture_company", True),
            plate_text=plate.text if plate else None,
        )
        direction = random.choice(["in", "out"]) if self._mock_mode else "unknown"
        self._commit(frame, bbox=det.bbox, vehicle_type=det.vehicle_type,
                     confidence=det.confidence, plate=plate, attrs=attrs,
                     direction=direction, settings=settings,
                     occupant_count=det.occupant_count)

    def _commit_tracked(self, ft, settings: dict) -> None:
        """Tracked path (real YOLO): log ONCE when a vehicle's track ends, using
        the clearest frame seen and the trajectory-derived direction.

        The plate is the FUSION of every OCR read collected while the vehicle
        was tracked (character-level voting across frames), not a single shot.
        """
        plate, plate_still = self._fused_plate(ft, settings)
        attrs = self.recognizer.recognize(
            ft.frame, ft.bbox,
            occupants=settings.get("capture_occupants", True),
            company=settings.get("capture_company", True),
            plate_text=plate.text if plate else None,
        )
        profile_still, fingerprint = self._vehicle_profile(ft)
        extra_meta = None
        if fingerprint:
            from .profiles import FINGERPRINT_VERSION
            extra_meta = {"profile_vec": fingerprint,
                          "profile_v": FINGERPRINT_VERSION}
        self._commit(ft.frame, bbox=ft.bbox, vehicle_type=ft.vehicle_type,
                     confidence=ft.confidence, plate=plate, attrs=attrs,
                     direction=ft.direction, settings=settings,
                     occupant_count=ft.occupant_count, plate_still=plate_still,
                     event_uuid=ft.event_uuid, pending=False,
                     profile_still=profile_still, extra_meta=extra_meta)

    def _commit_provisional(self, snap, settings: dict) -> None:
        """A vehicle just CONFIRMED in view → put it on the log NOW, with a
        photo and whatever the plate reads say so far. The same row is
        enriched (fused plate, direction, best frame) when the pass ends —
        `_commit_tracked` reuses the snapshot's event_uuid.

        Kept deliberately light: company OCR (the slow part) is skipped here
        and done once at finalize; color/occupants are cheap enough.
        """
        plate = None
        obs = list(snap.plate_observations or [])
        if obs:
            fused = fuse_observations(
                obs, format_correction=self.cfg.detector.alpr_format_correction)
            if fused is not None:
                plate = PlateResult(
                    text=fused.text, confidence=fused.confidence, region=fused.region,
                    char_confidences=fused.char_confidences,
                    region_confidence=fused.region_confidence,
                )
        attrs = self.recognizer.recognize(
            snap.frame, snap.bbox,
            occupants=settings.get("capture_occupants", True),
            company=False,
            plate_text=plate.text if plate else None,
        )
        self._commit(snap.frame, bbox=snap.bbox, vehicle_type=snap.vehicle_type,
                     confidence=snap.confidence, plate=plate, attrs=attrs,
                     direction=snap.direction, settings=settings,
                     occupant_count=snap.occupant_count,
                     event_uuid=snap.event_uuid, pending=True)

    def _fused_plate(self, ft, settings) -> tuple[Optional[PlateResult], Optional[bytes]]:
        """Consensus plate for a finished track + the best plate photo seen.

        Falls back to one read on the clearest frame when no reads were
        collected (vehicle stayed tiny, budget spent, plate never visible).
        """
        obs = list(ft.plate_observations or [])
        final = self._read_plate(ft.frame, ft.bbox, settings)
        final_obs = final.to_observation() if final else None
        if final_obs is not None:
            obs.append(final_obs)
        if not obs:
            return final, None

        fused = fuse_observations(
            obs, format_correction=self.cfg.detector.alpr_format_correction)
        if fused is None:
            return final, None
        if fused.corrected:
            logger.info("Plate format repair: %s -> %s (doubtful chars matched "
                        "a real plate layout)", fused.raw_text, fused.text)

        # The saved close-up = the sharpest/largest plate crop of the pass.
        plate_still = None
        best = best_crop_observation(obs)
        if best is not None and best.crop is not None:
            try:
                bh, bw = best.crop.shape[:2]
                plate_still = annotate.render_plate_crop(
                    best.crop, (0, 0, bw, bh), fused.text, fused.region)
            except Exception as exc:
                logger.debug("Best-shot plate render failed: %s", exc)

        # Keep the plate box only when it belongs to the committed frame.
        bbox = final.bbox if final and final.text and final.bbox else None
        result = PlateResult(
            text=fused.text, confidence=fused.confidence, region=fused.region,
            bbox=bbox, char_confidences=fused.char_confidences,
            region_confidence=fused.region_confidence,
        )
        logger.info("Plate consensus: %s (%.0f%%, %d read%s%s)",
                    fused.text, fused.confidence * 100, fused.reads,
                    "s" if fused.reads != 1 else "",
                    ", repaired" if fused.corrected else "")
        return result, plate_still

    def _collect_plate_reads(self, frame, tracked, settings: dict, det_seq: int) -> None:
        """Read the plate of each tracked vehicle on THIS frame and bank the
        result for fusion at track end. Budgeted per vehicle so a car idling
        in frame doesn't burn CPU forever."""
        if not tracked or self.tracker is None or self.plate_reader is None:
            return
        if not settings.get("capture_plate", True):
            return
        dcfg = self.cfg.detector
        read_every = max(1, int(getattr(dcfg, "alpr_read_every_n", 1) or 1))
        for det in tracked:
            if det.track_id is None:
                continue
            if not self.tracker.has_moved(det.track_id):
                continue  # parked car — don't burn OCR on scenery
            if (det.bbox[3] - det.bbox[1]) < dcfg.alpr_min_vehicle_px:
                continue  # too far away — the plate would be a smear
            if self.tracker.plate_read_count(det.track_id) >= dcfg.alpr_reads_per_track:
                continue  # budget spent for this vehicle
            lock_n = getattr(dcfg, "alpr_lock_after_agree", 0)
            if lock_n > 0 and self.tracker.plate_locked(det.track_id, min_agree=lock_n):
                continue  # consensus already locked — save the CPU for detection
            last_read = self._last_plate_read_seq.get(det.track_id, -10**9)
            if (det_seq - last_read) < read_every:
                continue
            blur_gate = getattr(dcfg, "alpr_skip_blur_below", 0.0)
            if blur_gate > 0:
                s = quick_sharpness(frame, det.bbox)
                if 0.0 <= s < blur_gate:
                    continue  # motion-blurred frame — a read would only add noise
            try:
                self._last_plate_read_seq[det.track_id] = det_seq
                res = self.plate_reader.read(frame, det.bbox)
            except Exception as exc:
                logger.debug("Per-frame plate read failed: %s", exc)
                continue
            obs = res.to_observation() if res else None
            if obs is not None:
                self.tracker.add_plate(det.track_id, obs,
                                       max_reads=dcfg.alpr_reads_per_track)

    # -- capture thread ---------------------------------------------------- #
    def _capture_loop(self) -> None:
        """Continuously grab frames and feed the live preview, independent of the
        (slower) detector. Keeps the live view smooth even while YOLO is busy."""
        cap_interval = 1.0 / _CAPTURE_FPS_CAP
        consecutive_failures = 0
        while self._running:
            t0 = time.monotonic()
            try:
                frame = self.camera.read()
            except Exception as exc:
                logger.warning("Camera read raised: %s", exc)
                frame = None

            if frame is None:
                consecutive_failures += 1
                if consecutive_failures >= _MAX_CONSECUTIVE_READ_FAILURES:
                    logger.error("%d consecutive camera failures - reinitialising.",
                                 consecutive_failures)
                    self._reinit_camera()
                    consecutive_failures = 0
                time.sleep(0.05)
                continue
            consecutive_failures = 0

            with self._frame_lock:
                self._latest_frame = frame
                self._frame_seq += 1
            self._frame_ready.set()
            self._frames += 1
            self._cap_fps.tick()

            if self.live is not None:
                self.live.submit(frame)  # best-effort live preview (non-blocking)

            dt = time.monotonic() - t0
            if dt < cap_interval:
                time.sleep(cap_interval - dt)

    # -- detection loop ---------------------------------------------------- #
    def run(self, duration: Optional[float] = None) -> None:
        assert self.camera and self.detector and self.events
        self._running = True
        self._capture_thread = threading.Thread(
            target=self._capture_loop, daemon=True, name="capture")
        self._capture_thread.start()

        interval = 1.0 / max(self.cfg.source.process_fps, 0.1)
        started = time.monotonic()
        last_seq = -1

        while self._running:
            loop_start = time.monotonic()
            if duration is not None and (loop_start - started) >= duration:
                logger.info("Reached run duration of %.1fs - stopping.", duration)
                break

            with self._frame_lock:
                frame = self._latest_frame
                seq = self._frame_seq
            if frame is None or seq == last_seq:
                # No new frame yet: sleep until the capture thread signals one
                # (with a timeout so shutdown is still noticed).
                self._frame_ready.wait(timeout=0.25)
                self._frame_ready.clear()
                continue
            last_seq = seq

            try:
                detections = self.detector.detect(frame)
            except Exception as exc:
                logger.warning("Detector error on frame %d: %s", seq, exc)
                detections = []
            detections = self._dedupe_detections(detections)
            self._det_fps.tick()
            self._det_seq += 1
            det_seq = self._det_seq
            if self.track_stabilizer is not None and not self._mock_mode:
                detections = self.track_stabilizer.stabilize(
                    detections, det_seq, frame_size(frame))

            settings = self._settings()
            self._annotate_occupants(detections, settings)
            # Untracked detections (mock detector) → debounced per-frame logging.
            for det in detections:
                if det.track_id is not None:
                    continue
                self._detections += 1
                try:
                    self._handle_detection(frame, det)
                except Exception as exc:
                    logger.warning("Failed to handle detection %s: %s", det, exc)

            # Tracked detections (real YOLO) → feed the manager; it logs each
            # vehicle once, on exit, with a direction.
            if self.tracker is not None:
                tracked = [d for d in detections
                           if d.track_id is not None and self._passes_filters(d, settings)]
                self._detections += len(tracked)
                try:
                    for ft in self.tracker.update(frame, tracked, det_seq):
                        try:
                            self._commit_tracked(ft, settings)
                        except Exception as exc:
                            logger.warning("Failed to commit track #%s: %s", ft.track_id, exc)
                except Exception as exc:
                    logger.warning("Tracker update failed: %s", exc)
                self._collect_plate_reads(frame, tracked, settings, det_seq)
                # A vehicle that just became real goes on the log IMMEDIATELY
                # (pending row) — the finalize above enriches it later.
                for snap in self.tracker.pop_new_confirmed():
                    if not getattr(self.cfg.events, "provisional_events", True):
                        continue
                    try:
                        self._commit_provisional(snap, settings)
                    except Exception as exc:
                        logger.warning("Provisional commit failed for track #%s: %s",
                                       snap.track_id, exc)

            # Hand this frame's boxes to the live preview (drawn over the
            # video so the owner can watch the AI work in real time).
            try:
                self._publish_overlay(frame, detections)
            except Exception:
                pass  # the overlay is cosmetic — never break detection

            elapsed = time.monotonic() - loop_start
            if elapsed < interval:
                time.sleep(interval - elapsed)

        self._running = False  # wind down the capture thread too

    def _reinit_camera(self) -> None:
        try:
            if self.camera:
                self.camera.release()
        except Exception:
            pass
        try:
            self.camera = create_camera(self.cfg.source, base_dir=self.cfg.base_dir)
            logger.info("Camera reinitialised: %s", self.camera.name)
        except CameraUnavailable as exc:
            logger.error("Camera reinit failed (%s); will keep retrying.", exc)
            time.sleep(2.0)

    # -- shutdown ---------------------------------------------------------- #
    def stop(self, *_args) -> None:
        self._running = False

    def shutdown(self) -> None:
        self._running = False
        if self._capture_thread and self._capture_thread.is_alive():
            self._capture_thread.join(timeout=2.0)
        # Log any vehicles still being tracked (last car before shutdown).
        if self.tracker is not None and self.events is not None:
            try:
                settings = self._settings()
                for ft in self.tracker.flush():
                    self._commit_tracked(ft, settings)
            except Exception as exc:
                logger.warning("Track flush on shutdown failed: %s", exc)
        logger.info("-" * 64)
        logger.info("Shutting down. Frames=%d Detections=%d Events logged=%d",
                    self._frames, self._detections, self._logged)
        if self.events:
            by_type = self.events.count_by_type()
            if by_type:
                logger.info("Events by type: %s", by_type)
            logger.info("DB totals: %d events (%d pending upload)",
                        self.events.count(), self.events.count_unsynced())
        if self.camera_config:
            self.camera_config.stop()
        if self.live:
            self.live.stop()
        if self.uploader:
            self.uploader.stop()
        if self.events:
            self.events.close()
        if self.camera:
            self.camera.release()
        logger.info("Goodbye.")


def build_app(config_path: Optional[str] = None, **overrides) -> SurveillanceApp:
    cfg = load_config(config_path)
    if overrides.get("source"):
        cfg.source.backend = overrides["source"]
    if overrides.get("backend"):
        cfg.detector.backend = overrides["backend"]
    if overrides.get("file"):
        cfg.source.backend = "file"
        cfg.source.file_path = overrides["file"]
    return SurveillanceApp(cfg)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="efsurveillance",
        description="EisenFieder Surveillance edge camera loop.",
    )
    parser.add_argument("--config", help="Path to config.yaml")
    parser.add_argument("--source", choices=["auto", "synthetic", "picamera2", "usb", "rtsp", "file"],
                        help="Override the video source")
    parser.add_argument("--file", help="Use this video file (sets source=file)")
    parser.add_argument("--backend", choices=["auto", "yolo", "mock"],
                        help="Override detector backend")
    parser.add_argument("--duration", type=float,
                        help="Run for N seconds then exit (default: until Ctrl-C)")
    args = parser.parse_args(argv)

    pre = load_config(args.config)
    setup_logging(pre.log_level)

    app = build_app(args.config, source=args.source, backend=args.backend, file=args.file)
    signal.signal(signal.SIGINT, app.stop)
    try:
        signal.signal(signal.SIGTERM, app.stop)
    except (ValueError, AttributeError):
        pass

    try:
        app.setup()
        app.run(duration=args.duration)
    except CameraUnavailable as exc:
        logger.error("Cannot start: %s", exc)
        return 2
    except KeyboardInterrupt:  # pragma: no cover
        pass
    finally:
        app.shutdown()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
