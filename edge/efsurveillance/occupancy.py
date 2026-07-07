"""Count vehicle occupants from person detections.

The YOLO detector reports ``person`` boxes alongside vehicles. A person is
counted as an occupant of a vehicle when the centre of their box falls inside
the vehicle's box (i.e. they are within the vehicle's footprint in the image).

This is a real measurement, but a best-effort one — a pedestrian walking
directly in front of a car can overlap it, and occupants in the back of a van
may not be visible at all. It is deliberately conservative: a person whose box
is larger than the vehicle box is treated as foreground clutter, not an
occupant. Nothing here is fabricated; when no person is seen inside, the count
is 0 (and the caller may leave it blank if occupant capture is disabled).
"""

from __future__ import annotations

from typing import Iterable, Sequence

Box = Sequence[int]


def _center(b: Box) -> tuple[float, float]:
    x1, y1, x2, y2 = b
    return (x1 + x2) / 2.0, (y1 + y2) / 2.0


def _area(b: Box) -> float:
    x1, y1, x2, y2 = b
    return max(0, (x2 - x1)) * max(0, (y2 - y1))


def count_occupants(vehicle_bbox: Box, person_boxes: Iterable[Box]) -> int:
    """Number of person boxes whose centre lies inside ``vehicle_bbox``.

    A person box larger than the vehicle box is ignored (foreground pedestrian
    occluding the vehicle rather than an occupant).
    """
    vx1, vy1, vx2, vy2 = vehicle_bbox
    v_area = _area(vehicle_bbox)
    count = 0
    for pb in person_boxes:
        cx, cy = _center(pb)
        if vx1 <= cx <= vx2 and vy1 <= cy <= vy2:
            if v_area == 0 or _area(pb) <= v_area:
                count += 1
    return count
