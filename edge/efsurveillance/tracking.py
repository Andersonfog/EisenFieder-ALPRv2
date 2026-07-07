"""Vehicle track lifecycle → one logged event per vehicle, with direction.

The detector assigns each vehicle a stable ``track_id`` across frames. This
manager watches each track and, once the vehicle leaves the frame (or has been
around long enough), emits a single :class:`FinalizedTrack` carrying:

  * the clearest frame seen (largest/closest box — best for plate OCR + the still),
  * the vehicle type and best confidence,
  * the travel **direction** (in / out / unknown) from its trajectory.

This replaces logging every frame: a car that drives through the entrance is
logged exactly once, and we know whether it was entering or leaving.

A track must also MOVE before it can become an event. A parked car sitting in
view is scenery, not a visit — and without this gate it would be re-logged
every time its track ended (age-out, or a passing vehicle briefly hiding it
and the tracker handing it a fresh id).

Direction is geometric: which way "in" points depends on how the camera is
mounted, so ``axis`` ("x" or "y") and ``invert`` are configurable.
"""

from __future__ import annotations

import logging
import math
import time
import uuid
from dataclasses import dataclass, field, replace
from typing import Any, Optional

from .camera import frame_size
from .plate_fusion import PlateObservation, consensus_locked
from .profiles import side_profile_score

logger = logging.getLogger(__name__)


def _copy_frame(frame: Any) -> Any:
    try:
        import numpy as np

        if isinstance(frame, np.ndarray):
            return frame.copy()
    except Exception:
        pass
    return frame  # SyntheticFrame / unknown — treat as immutable

def _iou(a: tuple, b: tuple) -> float:
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


def _center(bbox: tuple) -> tuple[float, float]:
    x1, y1, x2, y2 = (float(v) for v in bbox)
    return (x1 + x2) / 2.0, (y1 + y2) / 2.0


@dataclass
class _StableTrack:
    stable_id: int
    bbox: tuple
    last_seq: int
    external_id: Optional[int] = None
    vehicle_type: str = ""
    confidence: float = 0.0
    vx: float = 0.0
    vy: float = 0.0
    vw: float = 0.0
    vh: float = 0.0
    hits: int = 1


class TrackStabilizer:
    """Keep local track ids stable when YOLO boxes flicker or vanish briefly.

    This is deliberately lightweight: constant-velocity prediction, smoothed
    boxes, and greedy assignment. It gives the edge unit stable ids without
    paying ByteTrack's extra CPU cost on every frame.
    """

    def __init__(self, *, max_missing: int = 90, min_iou: float = 0.08,
                 max_center_dist_frac: float = 0.16,
                 smooth: float = 0.55) -> None:
        self.max_missing = max_missing
        self.min_iou = min_iou
        self.max_center_dist_frac = max_center_dist_frac
        self.smooth = max(0.0, min(0.95, smooth))
        self._next_id = 1
        self._tracks: dict[int, _StableTrack] = {}
        self._external_to_stable: dict[int, int] = {}

    def stabilize(self, detections, seq: int, frame_wh: tuple[int, int]) -> list:
        self._expire(seq)
        assigned: set[int] = set()
        out = []
        for det in sorted(detections, key=lambda d: getattr(d, "confidence", 0.0), reverse=True):
            stable_id = self._from_external(det, seq, frame_wh, assigned)
            if stable_id is None:
                stable_id = self._match(det.bbox, seq, frame_wh, assigned)
            if stable_id is None:
                stable_id = self._next_id
                self._next_id += 1
                self._tracks[stable_id] = _StableTrack(
                    stable_id=stable_id,
                    bbox=det.bbox,
                    last_seq=seq,
                    external_id=det.track_id,
                    vehicle_type=det.vehicle_type,
                    confidence=det.confidence,
                )
            else:
                self._update(stable_id, det, seq)
            assigned.add(stable_id)
            if det.track_id is not None:
                self._external_to_stable[int(det.track_id)] = stable_id
            try:
                out.append(replace(det, track_id=stable_id,
                                   bbox=self._tracks[stable_id].bbox))
            except Exception:
                det.track_id = stable_id
                det.bbox = self._tracks[stable_id].bbox
                out.append(det)
        return out

    def overlay_items(self, seq: int, frame_wh: tuple[int, int],
                      max_missing: int = 18) -> list[tuple[tuple, str, str]]:
        """Predicted/smoothed tracks for live overlay between detector frames."""
        items = []
        for track in self._tracks.values():
            missing = seq - track.last_seq
            if missing < 0 or missing > min(max_missing, self.max_missing):
                continue
            bbox = self._clip(self._predict(track, seq), frame_wh)
            label = f"{track.vehicle_type.upper() or 'VEHICLE'} #{track.stable_id}"
            items.append((bbox, label, "vehicle"))
        return items

    def _expire(self, seq: int) -> None:
        stale = [
            sid for sid, track in self._tracks.items()
            if (seq - track.last_seq) > self.max_missing
        ]
        for sid in stale:
            track = self._tracks.pop(sid, None)
            if track and track.external_id is not None:
                self._external_to_stable.pop(int(track.external_id), None)

    def _from_external(self, det, seq: int, frame_wh: tuple[int, int],
                       assigned: set[int]) -> Optional[int]:
        if det.track_id is None:
            return None
        stable_id = self._external_to_stable.get(int(det.track_id))
        if stable_id is None or stable_id in assigned:
            return None
        track = self._tracks.get(stable_id)
        if track is None or (seq - track.last_seq) > self.max_missing:
            return None
        if self._compatible(track.bbox, det.bbox, frame_wh):
            return stable_id
        return None

    def _match(self, bbox: tuple, seq: int, frame_wh: tuple[int, int],
               assigned: set[int]) -> Optional[int]:
        best_id = None
        best_score = -999.0
        for sid, track in self._tracks.items():
            if sid in assigned or (seq - track.last_seq) > self.max_missing:
                continue
            score = self._score(track, bbox, seq, frame_wh)
            if score > best_score:
                best_id, best_score = sid, score
        return best_id if best_score >= 0.0 else None

    def _compatible(self, old: tuple, new: tuple,
                    frame_wh: tuple[int, int]) -> bool:
        pseudo = _StableTrack(0, old, 0)
        return self._score(pseudo, new, 0, frame_wh) >= 0.0

    def _score(self, track: _StableTrack, new: tuple, seq: int,
               frame_wh: tuple[int, int]) -> float:
        predicted = self._predict(track, seq)
        overlap = _iou(predicted, new)
        ocx, ocy = _center(predicted)
        ncx, ncy = _center(new)
        w, h = frame_wh
        diag = max(1.0, math.hypot(float(w), float(h)))
        dist = math.hypot(ncx - ocx, ncy - ocy)
        dist_frac = dist / diag
        bw = max(1.0, float(predicted[2] - predicted[0]))
        bh = max(1.0, float(predicted[3] - predicted[1]))
        box_diag = max(24.0, math.hypot(bw, bh))
        dist_box = dist / box_diag
        if overlap >= self.min_iou:
            return overlap * 2.0 + max(0.0, 1.0 - dist_box) * 0.6
        if dist_box <= 1.0 or dist_frac <= self.max_center_dist_frac:
            return 0.35 + max(0.0, 1.0 - dist_box) * 0.4 - dist_frac
        return -1.0

    def _update(self, stable_id: int, det, seq: int) -> None:
        track = self._tracks[stable_id]
        dt = max(1, seq - track.last_seq)
        old_cx, old_cy = _center(track.bbox)
        new_cx, new_cy = _center(det.bbox)
        old_w = float(track.bbox[2] - track.bbox[0])
        old_h = float(track.bbox[3] - track.bbox[1])
        new_w = float(det.bbox[2] - det.bbox[0])
        new_h = float(det.bbox[3] - det.bbox[1])
        beta = 0.35
        track.vx = (1.0 - beta) * track.vx + beta * ((new_cx - old_cx) / dt)
        track.vy = (1.0 - beta) * track.vy + beta * ((new_cy - old_cy) / dt)
        track.vw = (1.0 - beta) * track.vw + beta * ((new_w - old_w) / dt)
        track.vh = (1.0 - beta) * track.vh + beta * ((new_h - old_h) / dt)
        s = self.smooth
        smoothed = tuple(
            int(round((s * float(old)) + ((1.0 - s) * float(new))))
            for old, new in zip(track.bbox, det.bbox)
        )
        track.bbox = smoothed
        track.last_seq = seq
        track.external_id = det.track_id
        track.vehicle_type = det.vehicle_type or track.vehicle_type
        track.confidence = max(track.confidence, det.confidence)
        track.hits += 1

    def _predict(self, track: _StableTrack, seq: int) -> tuple:
        dt = max(0, seq - track.last_seq)
        cx, cy = _center(track.bbox)
        w = float(track.bbox[2] - track.bbox[0])
        h = float(track.bbox[3] - track.bbox[1])
        cx += track.vx * dt
        cy += track.vy * dt
        w = max(8.0, w + track.vw * dt)
        h = max(8.0, h + track.vh * dt)
        return (
            int(round(cx - w / 2.0)),
            int(round(cy - h / 2.0)),
            int(round(cx + w / 2.0)),
            int(round(cy + h / 2.0)),
        )

    @staticmethod
    def _clip(bbox: tuple, frame_wh: tuple[int, int]) -> tuple:
        w, h = frame_wh
        x1, y1, x2, y2 = (int(v) for v in bbox)
        return (
            max(0, min(w, x1)),
            max(0, min(h, y1)),
            max(0, min(w, x2)),
            max(0, min(h, y2)),
        )


@dataclass
class _TrackState:
    track_id: int
    vehicle_type: str
    best_conf: float
    best_bbox: tuple
    best_frame: Any
    best_area: int
    best_occupants: Optional[int]
    first_cx: float
    first_cy: float
    last_cx: float
    last_cy: float
    last_seq: int
    frames: int
    first_time: float
    # One stable id per vehicle pass: the instant "vehicle arrived" event and
    # the final enriched event share it, so the log shows ONE row that updates.
    event_uuid: str = ""
    # True once the provisional "vehicle in view" event has been announced.
    announced: bool = False
    # Box area on the first sighting, and whether the vehicle has travelled /
    # approached enough to count as a real pass (vs a parked car).
    first_area: int = 0
    moved: bool = False
    # Best SIDE view seen (wide box = side-on): kept for the profile photo +
    # appearance fingerprint. Independent of best_frame (closest view).
    profile_score: float = 0.0
    profile_bbox: Optional[tuple] = None
    profile_frame: Any = None
    # Every OCR read of this vehicle's plate, for multi-frame fusion at commit.
    plates: list = field(default_factory=list)


@dataclass
class FinalizedTrack:
    track_id: int
    vehicle_type: str
    confidence: float
    bbox: tuple
    frame: Any
    direction: str  # "in" | "out" | "unknown"
    occupant_count: Optional[int] = None  # people seen inside, from the closest frame
    plate_observations: list = field(default_factory=list)  # all OCR reads, for fusion
    event_uuid: Optional[str] = None  # shared with the provisional event (same log row)
    profile_frame: Any = None         # frame with the best SIDE view of the pass
    profile_bbox: Optional[tuple] = None


class TrackManager:
    # A vehicle whose box grows/shrinks this much is approaching or leaving
    # head-on (real movement the centroid test can miss).
    _AREA_MOVE_RATIO = 1.8

    def __init__(self, *, axis: str = "x", invert: bool = False, miss_grace: int = 45,
                 min_frames: int = 2, move_frac: float = 0.12,
                 min_move_frac: float = 0.05,
                 max_age_seconds: float = 30.0) -> None:
        self.axis = "y" if str(axis).lower() == "y" else "x"
        self.invert = bool(invert)
        self.miss_grace = miss_grace          # detection cycles a track can be missing
        self.min_frames = min_frames          # ignore 1-frame blips (false positives)
        self.move_frac = move_frac            # min travel (fraction of frame) to call direction
        self.min_move_frac = min_move_frac    # min travel (fraction of frame) to BE an event
        self.max_age_seconds = max_age_seconds
        self._tracks: dict[int, _TrackState] = {}

    def update(self, frame, detections, seq: int, now: Optional[float] = None) -> list[FinalizedTrack]:
        """Feed one frame's tracked detections; return any tracks that just ended."""
        now = time.monotonic() if now is None else now
        for det in detections:
            if det.track_id is None:
                continue
            x1, y1, x2, y2 = det.bbox
            cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
            area = max(0, (x2 - x1)) * max(0, (y2 - y1))
            st = self._tracks.get(det.track_id)
            if st is None:
                first_copy = _copy_frame(frame)
                self._tracks[det.track_id] = _TrackState(
                    track_id=det.track_id, vehicle_type=det.vehicle_type,
                    best_conf=det.confidence, best_bbox=det.bbox, best_frame=first_copy,
                    best_area=area, best_occupants=det.occupant_count,
                    first_cx=cx, first_cy=cy, last_cx=cx, last_cy=cy,
                    last_seq=seq, frames=1, first_time=now,
                    event_uuid=str(uuid.uuid4()), first_area=area,
                    profile_score=side_profile_score(det.bbox),
                    profile_bbox=det.bbox, profile_frame=first_copy,
                )
                continue
            st.frames += 1
            st.last_cx, st.last_cy, st.last_seq = cx, cy, seq
            st.best_conf = max(st.best_conf, det.confidence)
            if not st.moved:
                w, h = frame_size(frame)
                span = max(w, h)
                frame_area = max(1, w * h)
                disp = ((cx - st.first_cx) ** 2 + (cy - st.first_cy) ** 2) ** 0.5
                grow = (area / st.first_area) if st.first_area > 0 else 1.0
                area_delta_frac = abs(area - st.first_area) / frame_area
                if (span > 0 and disp >= self.min_move_frac * span) \
                        or (st.frames >= 3 and area_delta_frac >= 0.02
                            and (grow >= self._AREA_MOVE_RATIO
                                 or grow <= (1.0 / self._AREA_MOVE_RATIO))):
                    st.moved = True
            if area >= st.best_area:  # keep the closest/clearest view
                st.best_area = area
                st.best_bbox = det.bbox
                st.best_frame = _copy_frame(frame)
                st.vehicle_type = det.vehicle_type
                st.best_occupants = det.occupant_count
            pscore = side_profile_score(det.bbox)
            if pscore > st.profile_score:  # keep the most side-on view
                st.profile_score = pscore
                st.profile_bbox = det.bbox
                st.profile_frame = _copy_frame(frame)

        finalized: list[FinalizedTrack] = []
        for tid in list(self._tracks):
            st = self._tracks[tid]
            if (seq - st.last_seq) > self.miss_grace or (now - st.first_time) > self.max_age_seconds:
                done = self._finalize(st)
                if done is not None:
                    finalized.append(done)
                del self._tracks[tid]
        return finalized

    def add_plate(self, track_id: int, obs: Optional[PlateObservation],
                  max_reads: int = 20) -> bool:
        """Attach one OCR read to a live track (returns False if unknown/full).

        ``max_reads`` bounds memory: a car idling in frame for minutes can't
        pile up unlimited crops. Once full, a new read only replaces the
        weakest stored one when it is clearly better.
        """
        st = self._tracks.get(track_id)
        if st is None or obs is None:
            return False
        if len(st.plates) < max_reads:
            st.plates.append(obs)
            return True
        weakest = min(range(len(st.plates)), key=lambda i: st.plates[i].confidence)
        if obs.confidence > st.plates[weakest].confidence:
            st.plates[weakest] = obs
            return True
        return False

    def plate_read_count(self, track_id: int) -> int:
        st = self._tracks.get(track_id)
        return len(st.plates) if st else 0

    def has_moved(self, track_id: int) -> bool:
        """True once this track has travelled/approached enough to be a real
        pass. Parked vehicles never do — callers can skip OCR etc. for them."""
        st = self._tracks.get(track_id)
        return bool(st and st.moved)

    def latest_plate_text(self, track_id: int) -> Optional[str]:
        """Best plate read so far for a LIVE track (for the preview overlay).
        Not the final answer — that's the fused consensus at commit time."""
        st = self._tracks.get(track_id)
        if st is None or not st.plates:
            return None
        best = max(st.plates, key=lambda o: o.confidence)
        return best.text or None

    def plate_locked(self, track_id: int, min_agree: int = 3,
                     min_conf: float = 0.92) -> bool:
        """True once this track's stored reads already agree confidently —
        more OCR can't change the answer, so the caller can stop paying for it."""
        st = self._tracks.get(track_id)
        if st is None:
            return False
        return consensus_locked(st.plates, min_agree=min_agree, min_conf=min_conf)

    def pop_new_confirmed(self) -> list[FinalizedTrack]:
        """Tracks that just became REAL (survived ``min_frames`` frames), each
        returned once. Lets the pipeline announce "a vehicle is here" the
        moment it's confirmed, instead of waiting for the pass to end — the
        snapshot carries the same ``event_uuid`` the final commit will use,
        so both land on one log row."""
        out: list[FinalizedTrack] = []
        for st in self._tracks.values():
            if st.announced or st.frames < self.min_frames or not st.moved:
                continue
            st.announced = True
            out.append(FinalizedTrack(
                track_id=st.track_id, vehicle_type=st.vehicle_type,
                confidence=st.best_conf, bbox=st.best_bbox, frame=st.best_frame,
                direction="unknown", occupant_count=st.best_occupants,
                plate_observations=list(st.plates), event_uuid=st.event_uuid,
            ))
        return out

    def flush(self) -> list[FinalizedTrack]:
        """Finalize all still-active tracks (call on shutdown)."""
        out = [self._finalize(st) for st in self._tracks.values()]
        self._tracks.clear()
        return [f for f in out if f is not None]

    def _finalize(self, st: _TrackState) -> Optional[FinalizedTrack]:
        if st.frames < self.min_frames:
            return None  # too brief to trust
        if not st.moved:
            # Parked/stationary the whole time: not a visit, so no event. This
            # also kills the re-log loop where a parked car got a fresh track
            # id (and a fresh log row) every time a passing vehicle hid it or
            # its track aged out.
            logger.debug("Track #%s stationary for %d frames - not logged (parked).",
                         st.track_id, st.frames)
            return None
        return FinalizedTrack(
            track_id=st.track_id, vehicle_type=st.vehicle_type, confidence=st.best_conf,
            bbox=st.best_bbox, frame=st.best_frame, direction=self._direction(st),
            occupant_count=st.best_occupants, plate_observations=st.plates,
            event_uuid=st.event_uuid,
            profile_frame=st.profile_frame, profile_bbox=st.profile_bbox,
        )

    def _direction(self, st: _TrackState) -> str:
        w, h = frame_size(st.best_frame)
        if self.axis == "y":
            delta, span = st.last_cy - st.first_cy, h
        else:
            delta, span = st.last_cx - st.first_cx, w
        if span <= 0 or abs(delta) < self.move_frac * span:
            return "unknown"
        positive = delta > 0
        if self.invert:
            positive = not positive
        return "in" if positive else "out"
