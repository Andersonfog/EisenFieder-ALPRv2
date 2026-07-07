"""License-plate reader (ALPR).

This is the headline capability. Two implementations:

    * :class:`MockPlateReader` — invents a plausible plate, no dependencies.
      Used for the laptop demo and tests.
    * :class:`RealPlateReader` — real plate detection + OCR via fast-alpr
      (ONNX, CPU-friendly). Returns a real reading or ``None`` — it never
      invents a plate.

What makes the real reader state-of-the-art rather than a one-shot OCR call:

    * **Per-character confidence** comes back with every read, so the fusion
      layer (:mod:`plate_fusion`) can vote character-by-character across the
      many frames of a vehicle's pass.
    * **Enhance-and-retry**: when the first read is doubtful, the plate crop
      is upscaled (small/distant plates) and contrast-boosted (shadow/glare),
      re-OCR'd, and the strongest read wins.
    * **Sharpness scoring** (variance of Laplacian) on every crop, so the
      fusion layer can weight crisp frames above blurry ones and the saved
      plate photo is the best one we captured.

``read(frame, bbox)`` is given the full frame and the vehicle's bounding box so
the plate search is focused on one vehicle.
"""

from __future__ import annotations

import logging
import random
import string
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional

from .plate_fusion import PlateObservation, fuse_observations

logger = logging.getLogger(__name__)

# US-ish region codes for the mock; a real reader returns the detected region.
REGIONS = ["CA", "TX", "NY", "FL", "WA", "OR", "AZ", "NV", "CO", "IL"]
_PLATE_LETTERS = "ABCDEFGHJKLMNPRSTUVWXYZ"  # no I/O/Q (ambiguous on plates)

# Below this mean per-character confidence, the enhance-and-retry pass runs.
_DEFAULT_RETRY_BELOW = 0.90
# Reads weaker than this are noise (a bumper sticker, half a plate) — dropped.
_DEFAULT_MIN_READ_CONF = 0.50
# Plates shorter than this after cleaning aren't plates.
_MIN_PLATE_CHARS = 3
# Deskew only clear tilts: below the min it's noise, above the max it's not a plate edge.
_MIN_TILT_DEG = 3.0
_MAX_TILT_DEG = 25.0
# CPU cap: at most this many enhanced variants are re-OCR'd per doubtful read.
_MAX_VARIANTS = 4


def quick_sharpness(frame, bbox=None, max_width: int = 160) -> float:
    """Cheap motion-blur check on a (downscaled) crop — Laplacian variance.

    Costs well under a millisecond, so the pipeline can skip a full OCR pass
    on frames that are too smeared to help. Returns -1.0 when it can't tell
    (no cv2 / synthetic frame) — callers must NOT skip on -1.0.
    """
    try:
        import cv2

        crop = frame
        if bbox is not None:
            h, w = frame.shape[:2]
            x1, y1, x2, y2 = (int(v) for v in bbox)
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(w, x2), min(h, y2)
            if x2 <= x1 or y2 <= y1:
                return -1.0
            crop = frame[y1:y2, x1:x2]
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
        if gray.shape[1] > max_width:
            scale = max_width / gray.shape[1]
            gray = cv2.resize(gray, None, fx=scale, fy=scale,
                              interpolation=cv2.INTER_AREA)
        return float(cv2.Laplacian(gray, cv2.CV_64F).var())
    except Exception:
        return -1.0


@dataclass
class PlateResult:
    text: Optional[str]
    confidence: float = 0.0
    region: Optional[str] = None
    bbox: Optional[tuple] = None  # (x1,y1,x2,y2) plate box in full-frame coords, when known
    char_confidences: list[float] = field(default_factory=list)  # aligned to text
    region_confidence: Optional[float] = None
    sharpness: float = 0.0        # Laplacian variance of the plate crop
    crop: Any = None              # BGR ndarray of the plate pixels, when available

    def to_observation(self) -> Optional[PlateObservation]:
        """Package this read for multi-frame fusion (None when nothing was read)."""
        if not self.text:
            return None
        clean = "".join(ch for ch in self.text if ch.isalnum()).upper()
        if not clean:
            return None
        # Keep confidences aligned when cleaning removed characters (dashes).
        confs = self.char_confidences
        if confs and len(confs) == len(self.text) and len(clean) != len(self.text):
            confs = [c for ch, c in zip(self.text, confs) if ch.isalnum()]
        height = 0
        if self.bbox is not None:
            height = max(0, int(self.bbox[3]) - int(self.bbox[1]))
        return PlateObservation(
            text=clean,
            char_confidences=list(confs) if confs else [],
            confidence=self.confidence,
            region=self.region,
            region_confidence=self.region_confidence,
            plate_height=height,
            sharpness=self.sharpness,
            bbox=self.bbox,
            crop=self.crop,
        )


class BasePlateReader(ABC):
    name = "base"

    @abstractmethod
    def read(self, frame, bbox) -> PlateResult:
        ...


class MockPlateReader(BasePlateReader):
    name = "mock"

    def read(self, frame, bbox) -> PlateResult:
        # Most vehicles read a plate; some are unreadable (angle/glare) -> None.
        if random.random() < 0.1:
            return PlateResult(text=None, confidence=0.0, region=None)
        text = (
            "".join(random.choice(_PLATE_LETTERS) for _ in range(3))
            + "-"
            + "".join(random.choice(string.digits) for _ in range(4))
        )
        return PlateResult(text=text, confidence=round(random.uniform(0.80, 0.99), 2),
                           region=random.choice(REGIONS))


class RealPlateReader(BasePlateReader):
    """Real license-plate OCR via fast-alpr (ONNX, runs on CPU or a Pi).

    Returns a real reading or ``None`` — it never invents a plate. If the engine
    can't be loaded, every read is a clean ``None`` (no fake data).
    """

    name = "real"

    def __init__(self, *, retry_below_conf: float = _DEFAULT_RETRY_BELOW,
                 min_read_conf: float = _DEFAULT_MIN_READ_CONF) -> None:
        self.retry_below_conf = retry_below_conf
        self.min_read_conf = min_read_conf
        self._alpr = None
        try:  # pragma: no cover - needs the ALPR engine installed
            from fast_alpr import ALPR

            logger.info("PlateReader: loading fast-alpr models "
                        "(first run downloads them, then they're cached)…")
            self._alpr = ALPR()
            logger.info("PlateReader: fast-alpr ready — real license-plate OCR.")
        except Exception as exc:
            logger.warning(
                "PlateReader: real ALPR unavailable (%s). Plates will be blank "
                "(never faked). Install with: pip install fast-alpr", exc,
            )

    # -- helpers ------------------------------------------------------------ #
    @staticmethod
    def _clean_text(raw: str) -> tuple[str, list[int]]:
        """Uppercase A-Z/0-9 only; returns (clean, kept source indices) so the
        per-character confidences can be re-aligned after cleaning."""
        out, kept = [], []
        for i, ch in enumerate(raw):
            if ch.isalnum():
                out.append(ch.upper())
                kept.append(i)
        return "".join(out), kept

    @staticmethod
    def _conf_list(ocr, text_len: int) -> list[float]:
        """Per-character confidences aligned to the (pad-stripped) OCR text.

        fast-plate-ocr returns one confidence per model SLOT (fixed width, e.g.
        9), while the text has trailing padding removed — so trim to the text.
        """
        conf = getattr(ocr, "confidence", None)
        if isinstance(conf, (list, tuple)):
            return [float(c) for c in conf[:text_len]]
        if conf is None:
            return []
        return [float(conf)] * text_len

    @staticmethod
    def _region(value) -> Optional[str]:
        """The global OCR model labels most plates region 'Unknown' — store an
        honest blank instead of that placeholder string."""
        if not value or str(value).strip().lower() in {"unknown", "none"}:
            return None
        return str(value)

    @staticmethod
    def _sharpness(crop) -> float:
        try:
            import cv2

            gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
            return float(cv2.Laplacian(gray, cv2.CV_64F).var())
        except Exception:
            return 0.0

    @staticmethod
    def _estimate_tilt(plate_crop) -> float:
        """Tilt of the plate in degrees, from its dominant near-horizontal
        edges (the plate frame and the character baseline). 0.0 = level or
        can't tell."""
        try:
            import math

            import cv2

            gray = (cv2.cvtColor(plate_crop, cv2.COLOR_BGR2GRAY)
                    if plate_crop.ndim == 3 else plate_crop)
            h, w = gray.shape[:2]
            if w < 40 or h < 12:
                return 0.0
            edges = cv2.Canny(gray, 60, 180)
            lines = cv2.HoughLinesP(edges, 1, math.pi / 180.0,
                                    threshold=max(15, w // 5),
                                    minLineLength=int(w * 0.4), maxLineGap=6)
            if lines is None:
                return 0.0
            angles = []
            for x1, y1, x2, y2 in (ln[0] for ln in lines):
                dx, dy = x2 - x1, y2 - y1
                if dx == 0:
                    continue
                if dx < 0:  # endpoint order isn't guaranteed — read left-to-right
                    dx, dy = -dx, -dy
                ang = math.degrees(math.atan2(dy, dx))
                if abs(ang) <= _MAX_TILT_DEG:
                    angles.append(ang)
            if not angles:
                return 0.0
            angles.sort()
            return float(angles[len(angles) // 2])  # median: robust to strays
        except Exception:
            return 0.0

    @staticmethod
    def _rotated_level(plate_crop, angle_deg: float):
        """The crop rotated so a plate tilted by ``angle_deg`` reads level."""
        try:
            import cv2

            h, w = plate_crop.shape[:2]
            m = cv2.getRotationMatrix2D((w / 2.0, h / 2.0), angle_deg, 1.0)
            return cv2.warpAffine(plate_crop, m, (w, h), flags=cv2.INTER_CUBIC,
                                  borderMode=cv2.BORDER_REPLICATE)
        except Exception:
            return None

    @classmethod
    def _enhanced_variants(cls, plate_crop) -> list:
        """Cheap image repairs for a doubtful read, each re-OCR'd (capped at
        ``_MAX_VARIANTS`` for CPU): deskew a tilted plate, upscale small crops
        (the OCR wants tall characters), boost local contrast (shadow/glare),
        sharpen mild blur, and fix over/under-exposure.
        """
        variants: list = []
        try:
            import cv2
            import numpy as np

            base = plate_crop
            # Tilted plate (angled mount / turning car)? Level it first —
            # every later enhancement then works on the straightened image.
            tilt = cls._estimate_tilt(base)
            if _MIN_TILT_DEG <= abs(tilt) <= _MAX_TILT_DEG:
                level = cls._rotated_level(base, tilt)
                if level is not None:
                    base = level
                    variants.append(level)

            h = base.shape[0]
            if h and h < 64:
                scale = min(3.0, 64.0 / h)
                base = cv2.resize(base, None, fx=scale, fy=scale,
                                  interpolation=cv2.INTER_CUBIC)
                variants.append(base)

            gray = cv2.cvtColor(base, cv2.COLOR_BGR2GRAY)
            clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
            variants.append(cv2.cvtColor(clahe.apply(gray), cv2.COLOR_GRAY2BGR))

            if len(variants) < _MAX_VARIANTS:
                # Unsharp mask: recovers mildly soft focus / slight motion blur.
                blur = cv2.GaussianBlur(base, (0, 0), 2.0)
                variants.append(cv2.addWeighted(base, 1.6, blur, -0.6, 0))

            if len(variants) < _MAX_VARIANTS:
                mean = float(gray.mean())
                if mean < 70 or mean > 185:  # night shot vs washed-out glare
                    g = 0.6 if mean < 70 else 1.7
                    lut = np.array([((i / 255.0) ** g) * 255 for i in range(256)],
                                   dtype="uint8")
                    variants.append(cv2.LUT(base, lut))
        except Exception:
            pass
        return variants[:_MAX_VARIANTS]

    def _mean_conf(self, confs: list[float], fallback: float = 0.0) -> float:
        return (sum(confs) / len(confs)) if confs else fallback

    # -- main read ----------------------------------------------------------- #
    def read(self, frame, bbox) -> PlateResult:
        if self._alpr is None or getattr(frame, "shape", None) is None:
            return PlateResult(text=None)
        try:
            h, w = frame.shape[:2]
            x1, y1, x2, y2 = (int(v) for v in bbox)
            # Crop to the vehicle (plus a small margin) so the plate search
            # focuses there and small plates stay as large as possible.
            mx, my = int((x2 - x1) * 0.05), int((y2 - y1) * 0.05)
            cx1, cy1 = max(0, x1 - mx), max(0, y1 - my)
            cx2, cy2 = min(w, x2 + mx), min(h, y2 + my)
            crop = frame[cy1:cy2, cx1:cx2]
            if crop.size == 0:
                return PlateResult(text=None)

            best = None  # (mean_conf, text, confs, plate_bbox_in_crop, region, region_conf)
            for r in self._alpr.predict(crop):
                ocr = getattr(r, "ocr", None)
                raw = getattr(ocr, "text", None) if ocr else None
                if not raw:
                    continue
                clean, kept = self._clean_text(raw)
                if len(clean) < _MIN_PLATE_CHARS:
                    continue
                confs_raw = self._conf_list(ocr, len(raw))
                confs = [confs_raw[i] for i in kept if i < len(confs_raw)] or confs_raw
                mean = self._mean_conf(confs)
                if best is None or mean > best[0]:
                    best = (mean, clean, confs, r.detection.bounding_box,
                            self._region(getattr(ocr, "region", None)),
                            getattr(ocr, "region_confidence", None))
            if best is None:
                return PlateResult(text=None)

            mean, text, confs, bb, region, region_conf = best

            # Extract the plate pixels (small margin) for sharpness scoring,
            # the enhance-and-retry pass, and the saved close-up photo.
            ch, cw = crop.shape[:2]
            pmx = max(2, int((bb.x2 - bb.x1) * 0.08))
            pmy = max(2, int((bb.y2 - bb.y1) * 0.15))
            px1, py1 = max(0, bb.x1 - pmx), max(0, bb.y1 - pmy)
            px2, py2 = min(cw, bb.x2 + pmx), min(ch, bb.y2 + pmy)
            plate_crop = crop[py1:py2, px1:px2].copy() if px2 > px1 and py2 > py1 else None
            sharp = self._sharpness(plate_crop) if plate_crop is not None else 0.0

            # Doubtful first read? Enhance the crop (deskew/upscale/contrast/
            # sharpen) and re-OCR each variant. All the reads of THIS frame
            # are then merged character-by-character — variant A may nail the
            # left half while variant B nails the right — and the merge is
            # kept only when it beats the best single read. Never invention:
            # every character came from an actual OCR read of these pixels.
            if mean < self.retry_below_conf and plate_crop is not None:
                ph = int(plate_crop.shape[0])
                frame_reads = [PlateObservation(text, list(confs), mean,
                                                plate_height=ph, sharpness=sharp)]
                for variant in self._enhanced_variants(plate_crop):
                    try:
                        ocr2 = self._alpr.ocr.predict(variant)
                    except Exception:
                        continue
                    raw2 = getattr(ocr2, "text", None) if ocr2 else None
                    if not raw2:
                        continue
                    clean2, kept2 = self._clean_text(raw2)
                    if len(clean2) < _MIN_PLATE_CHARS:
                        continue
                    confs2_raw = self._conf_list(ocr2, len(raw2))
                    confs2 = [confs2_raw[i] for i in kept2 if i < len(confs2_raw)] or confs2_raw
                    mean2 = self._mean_conf(confs2)
                    frame_reads.append(PlateObservation(clean2, list(confs2), mean2,
                                                        plate_height=ph, sharpness=sharp))
                    if mean2 > mean:
                        mean, text, confs = mean2, clean2, confs2
                        region = self._region(getattr(ocr2, "region", None)) or region
                        region_conf = getattr(ocr2, "region_confidence", None) or region_conf
                if len(frame_reads) >= 2:
                    merged = fuse_observations(frame_reads, format_correction=False)
                    if merged is not None and merged.confidence > mean:
                        mean, text, confs = (merged.confidence, merged.text,
                                             list(merged.char_confidences))

            # Too weak to trust at all -> honest None (fusion can't fix noise).
            if mean < self.min_read_conf:
                return PlateResult(text=None)

            # Map the plate box back to full-frame coordinates.
            pbox = (cx1 + bb.x1, cy1 + bb.y1, cx1 + bb.x2, cy1 + bb.y2)
            return PlateResult(
                text=text, confidence=round(mean, 4), region=region, bbox=pbox,
                char_confidences=[round(c, 4) for c in confs],
                region_confidence=region_conf, sharpness=round(sharp, 2),
                crop=plate_crop,
            )
        except Exception as exc:
            logger.debug("ALPR read failed: %s", exc)
            return PlateResult(text=None)


def create_plate_reader(backend: str = "auto", detector_cfg=None) -> BasePlateReader:
    backend = (backend or "auto").lower()
    if backend == "mock":
        return MockPlateReader()
    # Real for everything else (yolo / real / auto) — real plates or honest None.
    kwargs = {}
    if detector_cfg is not None:
        kwargs = {
            "retry_below_conf": getattr(detector_cfg, "alpr_retry_below_conf",
                                        _DEFAULT_RETRY_BELOW),
            "min_read_conf": getattr(detector_cfg, "alpr_min_read_conf",
                                     _DEFAULT_MIN_READ_CONF),
        }
    return RealPlateReader(**kwargs)
