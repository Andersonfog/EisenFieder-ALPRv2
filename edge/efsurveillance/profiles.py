"""Vehicle appearance profiles — the side-view photo + a compact "fingerprint".

Why side profiles? Vehicle re-identification research consistently finds the
most viewpoint-robust cues are COLOR, SHAPE and TYPE, and the side view shows
the most of all three (body line, window line, wheels). So during a vehicle's
pass we keep the most side-on frame we saw, store that crop with the event,
and boil its appearance down to a small vector:

    * HSV colour histogram of the body (what colour, how saturated),
    * a coarse HOG-style gradient grid (the shape: roofline, windows, wheels),
    * geometry (how long-vs-tall the vehicle is).

Two fingerprints are compared with cosine similarity. This is a deliberately
classical, CPU-cheap design (no ML, runs fine on a Pi) and it is HONEST about
what it is: "these two vehicles LOOK alike (82%)" is a suggestion for the
owner, never an identity claim — license plates do identity.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Fingerprint layout (bump the version if any of this changes — vectors of
# different versions must not be compared).
FINGERPRINT_VERSION = 1
_H_BINS, _S_BINS = 12, 4          # colour: hue x saturation histogram
_NORM_W, _NORM_H = 64, 32         # shape: gray crop normalized to this size
_GRID_ROWS, _GRID_COLS = 4, 4     # shape: cells over the normalized crop
_ORI_BINS = 6                     # shape: gradient-orientation bins per cell
# Block weights: colour separates most vehicles, shape breaks colour ties.
_W_COLOR, _W_SHAPE, _W_GEOM = 0.5, 0.42, 0.08


def side_profile_score(bbox) -> float:
    """How good this view is as a SIDE profile.

    Side views of vehicles are wide (width/height around 2.0-2.8); front and
    rear views are square-ish. Peak preference at ~2.4, scaled by size so a
    close, detailed view beats a distant sliver.
    """
    x1, y1, x2, y2 = bbox
    w, h = max(1, x2 - x1), max(1, y2 - y1)
    aspect = w / h
    if aspect <= 1.1 or aspect >= 4.0:
        shape = 0.05          # head-on / tail-on / something weird
    elif aspect <= 2.4:
        shape = (aspect - 1.1) / 1.3
    else:
        shape = max(0.05, 1.0 - (aspect - 2.4) / 1.6)
    return shape * (w * h) ** 0.5


def compute_fingerprint(crop: Any) -> Optional[list[float]]:
    """Appearance vector for a vehicle crop (BGR ndarray) — or None, honestly,
    when the crop is unusable. Deterministic: same pixels, same vector."""
    try:
        import cv2
        import numpy as np
    except Exception:
        return None
    if getattr(crop, "shape", None) is None or crop.ndim != 3:
        return None
    h0, w0 = crop.shape[:2]
    if h0 < 16 or w0 < 16:
        return None  # too tiny to say anything honest about appearance

    try:
        # --- colour: HSV histogram of the central body region (margins cut
        # away road/background pixels the box always includes). -------------
        my, mx = int(h0 * 0.14), int(w0 * 0.10)
        body = crop[my:h0 - my or h0, mx:w0 - mx or w0]
        if body.size == 0:
            body = crop
        hsv = cv2.cvtColor(body, cv2.COLOR_BGR2HSV)
        hist = cv2.calcHist([hsv], [0, 1], None, [_H_BINS, _S_BINS],
                            [0, 180, 0, 256]).flatten().astype("float64")
        n = np.linalg.norm(hist)
        color_vec = (hist / n if n else hist) * _W_COLOR

        # --- shape: coarse gradient-orientation grid on the normalized gray
        # crop (a tiny HOG). Captures roofline/windows/wheel arches. ---------
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        norm = cv2.resize(gray, (_NORM_W, _NORM_H), interpolation=cv2.INTER_AREA)
        gx = cv2.Sobel(norm, cv2.CV_32F, 1, 0, ksize=3)
        gy = cv2.Sobel(norm, cv2.CV_32F, 0, 1, ksize=3)
        mag = np.sqrt(gx * gx + gy * gy)
        ang = np.mod(np.arctan2(gy, gx), np.pi)  # unsigned orientation 0..pi
        cell_h, cell_w = _NORM_H // _GRID_ROWS, _NORM_W // _GRID_COLS
        cells: list[float] = []
        for r in range(_GRID_ROWS):
            for c in range(_GRID_COLS):
                m = mag[r * cell_h:(r + 1) * cell_h, c * cell_w:(c + 1) * cell_w]
                a = ang[r * cell_h:(r + 1) * cell_h, c * cell_w:(c + 1) * cell_w]
                hist_c, _ = np.histogram(a, bins=_ORI_BINS, range=(0.0, np.pi),
                                         weights=m)
                cells.extend(hist_c.tolist())
        shape_arr = np.asarray(cells, dtype="float64")
        n = np.linalg.norm(shape_arr)
        shape_vec = (shape_arr / n if n else shape_arr) * _W_SHAPE

        # --- geometry: how long-vs-tall (clamped so one number can't dominate).
        aspect = min(4.0, w0 / h0) / 4.0
        geom = np.asarray([aspect, 1.0 - aspect], dtype="float64")
        n = np.linalg.norm(geom)
        geom_vec = (geom / n if n else geom) * _W_GEOM

        vec = np.concatenate([color_vec, shape_vec, geom_vec])
        return [round(float(v), 5) for v in vec]
    except Exception as exc:
        logger.debug("Fingerprint failed: %s", exc)
        return None


def similarity(a: Optional[list], b: Optional[list]) -> float:
    """Cosine similarity between two fingerprints, 0.0-1.0. Vectors of
    different lengths (different versions) honestly compare as 0."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    if not na or not nb:
        return 0.0
    return max(0.0, min(1.0, dot / (na * nb)))
