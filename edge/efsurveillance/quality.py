"""ALPR capture profiles tuned for Raspberry Pi 5 edge units."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class QualityProfile:
    id: str
    label: str
    width: int
    height: int
    fps: float
    process_fps: float
    live_fps: float
    live_max_width: int
    live_jpeg_quality: int
    fourcc: str
    shutter_us: int
    analogue_gain: float
    denoise: str
    alpr_reads_per_track: int
    alpr_min_vehicle_px: int
    alpr_skip_blur_below: float
    alpr_read_every_n: int


PROFILES: dict[str, QualityProfile] = {
    "sharp_read": QualityProfile(
        id="sharp_read",
        label="Sharp read",
        width=2304,
        height=1296,
        fps=24.0,
        process_fps=12.0,
        live_fps=12.0,
        live_max_width=1280,
        live_jpeg_quality=78,
        fourcc="MJPG",
        shutter_us=1000,
        analogue_gain=1.5,
        denoise="cdn_fast",
        alpr_reads_per_track=14,
        alpr_min_vehicle_px=50,
        alpr_skip_blur_below=10.0,
        alpr_read_every_n=2,
    ),
    "fast_lane": QualityProfile(
        id="fast_lane",
        label="Fast lane",
        width=1920,
        height=1080,
        fps=60.0,
        process_fps=30.0,
        live_fps=20.0,
        live_max_width=960,
        live_jpeg_quality=74,
        fourcc="MJPG",
        shutter_us=667,
        analogue_gain=1.0,
        denoise="off",
        alpr_reads_per_track=8,
        alpr_min_vehicle_px=54,
        alpr_skip_blur_below=14.0,
        alpr_read_every_n=3,
    ),
    "track_boost": QualityProfile(
        id="track_boost",
        label="Track boost",
        width=1280,
        height=720,
        fps=60.0,
        process_fps=45.0,
        live_fps=30.0,
        live_max_width=960,
        live_jpeg_quality=72,
        fourcc="MJPG",
        shutter_us=667,
        analogue_gain=1.0,
        denoise="off",
        alpr_reads_per_track=6,
        alpr_min_vehicle_px=64,
        alpr_skip_blur_below=14.0,
        alpr_read_every_n=4,
    ),
    "night_boost": QualityProfile(
        id="night_boost",
        label="Night boost",
        width=1920,
        height=1080,
        fps=20.0,
        process_fps=10.0,
        live_fps=10.0,
        live_max_width=960,
        live_jpeg_quality=80,
        fourcc="MJPG",
        shutter_us=2000,
        analogue_gain=4.0,
        denoise="cdn_hq",
        alpr_reads_per_track=16,
        alpr_min_vehicle_px=48,
        alpr_skip_blur_below=6.0,
        alpr_read_every_n=2,
    ),
    "pi_economy": QualityProfile(
        id="pi_economy",
        label="Pi economy",
        width=1280,
        height=720,
        fps=30.0,
        process_fps=8.0,
        live_fps=8.0,
        live_max_width=720,
        live_jpeg_quality=68,
        fourcc="MJPG",
        shutter_us=1333,
        analogue_gain=2.0,
        denoise="cdn_fast",
        alpr_reads_per_track=8,
        alpr_min_vehicle_px=56,
        alpr_skip_blur_below=8.0,
        alpr_read_every_n=4,
    ),
}


def profile_for(profile_id: str | None) -> QualityProfile | None:
    if not profile_id:
        return None
    key = str(profile_id).strip().lower().replace("-", "_")
    if key in {"", "custom", "manual"}:
        return None
    return PROFILES.get(key)


def profile_options() -> list[dict]:
    purpose = {
        "sharp_read": "plate detail",
        "fast_lane": "motion freeze",
        "track_boost": "smooth tracking",
        "night_boost": "low light / IR",
        "pi_economy": "low heat",
    }
    return [
        {
            "id": p.id,
            "label": p.label,
            "resolution": f"{p.width}x{p.height}",
            "fps": p.fps,
            "process_fps": p.process_fps,
            "purpose": purpose.get(p.id, "custom"),
        }
        for p in PROFILES.values()
    ]
