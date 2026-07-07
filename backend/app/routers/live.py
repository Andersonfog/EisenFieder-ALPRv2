"""Live camera preview (owner-only).

A camera can push a low-frame-rate JPEG preview here so the owner can check the
angle and framing from the console - without walking out to the entrance. The
preview is held in memory only: it is never written to disk and never added to
the event history. It is served only to the authenticated owner.

This is a *preview*, not a recording: a few frames per second, latest-only.

Single-process / single-tenant by design - the latest frame per camera lives in
a module-level dict. (If you ever run the API with multiple worker processes,
move this to Redis or a shared file; otherwise each worker keeps its own copy.)
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Camera, User
from ..security import get_current_user, require_camera_auth, require_owner

router = APIRouter(prefix="/api/v1/cameras", tags=["live"])

# camera_id -> (jpeg_bytes, epoch_seconds, stats)
_LATEST: dict[str, tuple[bytes, float, dict]] = {}

# camera_id -> event that fires when that camera pushes its next frame. Streams
# sleep on this instead of polling, so a frame is forwarded the moment it lands
# and an idle stream costs (almost) nothing. Each push consumes the event and
# waiters create a fresh one - a simple one-shot broadcast.
_FRAME_EVENTS: dict[str, asyncio.Event] = {}

# multipart/x-mixed-replace boundary.
_MJPEG_BOUNDARY = b"efsframe"
# While waiting for a frame, wake at least this often to notice a dropped client.
_STREAM_IDLE_WAKE_SECONDS = 1.0
# Cap concurrent open MJPEG streams so a handful of stuck/duplicate viewers
# can't tie up resources indefinitely (single-tenant: a few tabs is plenty).
_MAX_CONCURRENT_STREAMS = 8
_active_streams = 0


def _f(value) -> float | None:
    try:
        return round(float(value), 1)
    except (TypeError, ValueError):
        return None


def _stats_from_headers(request: Request) -> dict:
    stats = {
        "capture_fps": _f(request.headers.get("X-Capture-FPS")),
        "detect_fps": _f(request.headers.get("X-Detect-FPS")),
    }
    header_map = {
        "profile": "X-ALPR-Profile",
        "source_fps": "X-Source-FPS",
        "frame_width": "X-Frame-Width",
        "frame_height": "X-Frame-Height",
        "live_quality": "X-Live-Quality",
        "cpu_temp_c": "X-CPU-Temp-C",
        "queued": "X-Queued-Events",
    }
    for key, header in header_map.items():
        raw = request.headers.get(header)
        if raw is None:
            continue
        if key in {"profile"}:
            stats[key] = raw
        elif key in {"frame_width", "frame_height", "live_quality", "queued"}:
            try:
                stats[key] = int(float(raw))
            except ValueError:
                stats[key] = None
        else:
            stats[key] = _f(raw)
    return stats


def _parse_packet_stats(parts: list[bytes]) -> dict:
    stats = {
        "capture_fps": _f(parts[2].decode()) if len(parts) > 2 else None,
        "detect_fps": _f(parts[3].decode()) if len(parts) > 3 else None,
    }
    for token in parts[4:]:
        if b"=" not in token:
            continue
        key_b, value_b = token.split(b"=", 1)
        key = key_b.decode(errors="ignore")
        raw = value_b.decode(errors="ignore").replace("_", " ")
        if key == "profile":
            stats[key] = raw.replace(" ", "_")
        elif key in {"frame_width", "frame_height", "live_quality", "queued"}:
            try:
                stats[key] = int(float(raw))
            except ValueError:
                stats[key] = None
        elif key in {"source_fps", "cpu_temp_c"}:
            stats[key] = _f(raw)
    return stats

# A preview older than this means the camera stopped pushing (offline).
STALE_SECONDS = 15.0
# Reject absurd uploads (a 640px preview JPEG is ~30-80 KB; leave headroom).
MAX_FRAME_BYTES = 3_000_000


def _touch_camera(camera_id: str, db: Session) -> None:
    """Ensure a live-only USB camera appears in the console camera list."""
    camera = db.get(Camera, camera_id)
    if camera is None:
        camera = Camera(id=camera_id, name=camera_id, status="online")
        db.add(camera)
    else:
        camera.status = "online"
    camera.last_seen = datetime.now(timezone.utc)
    db.commit()


@router.post("/{camera_id}/live", status_code=status.HTTP_204_NO_CONTENT)
async def push_live_frame(
    request: Request,
    camera_id: str = Depends(require_camera_auth),
    db: Session = Depends(get_db),
):
    """The edge unit pushes its latest JPEG preview (camera-authenticated).

    The authenticated camera id is used as the key, so a camera can only write
    its own preview (the path id is ignored on purpose).
    """
    # Reject oversized uploads BEFORE buffering anything: first on the declared
    # Content-Length, then again while streaming (a client can lie about the
    # header, so the cap is enforced on the actual bytes too).
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_FRAME_BYTES:
        raise HTTPException(status_code=413, detail="Frame too large")
    chunks: list[bytes] = []
    received = 0
    async for chunk in request.stream():
        received += len(chunk)
        if received > MAX_FRAME_BYTES:
            raise HTTPException(status_code=413, detail="Frame too large")
        chunks.append(chunk)
    data = b"".join(chunks)
    if not data:
        raise HTTPException(status_code=400, detail="Empty frame")
    if data[:2] != b"\xff\xd8":  # JPEG start-of-image marker
        raise HTTPException(status_code=415, detail="Expected a JPEG frame")
    _touch_camera(camera_id, db)
    _store_frame(camera_id, data, _stats_from_headers(request))


def _store_frame(camera_id: str, data: bytes, stats: dict) -> None:
    """Publish a camera's newest frame and wake every waiting MJPEG stream."""
    _LATEST[camera_id] = (data, time.time(), stats)
    waiter = _FRAME_EVENTS.pop(camera_id, None)
    if waiter is not None:
        waiter.set()


@router.post("/{camera_id}/live/stream", status_code=status.HTTP_204_NO_CONTENT)
async def push_live_stream(
    request: Request,
    camera_id: str = Depends(require_camera_auth),
    db: Session = Depends(get_db),
):
    """The edge unit streams ALL its preview frames over ONE held-open upload
    (camera-authenticated) instead of one HTTP request per frame.

    Wire format per frame (see edge live.frame_packet):

        EFSF <jpeg_length> <capture_fps> <detect_fps>\\n<jpeg bytes>

    Frames are published to the same in-memory slot the per-frame POST uses,
    so the owner-facing MJPEG stream doesn't care which mode the camera runs.
    """
    _touch_camera(camera_id, db)
    buf = bytearray()
    async for chunk in request.stream():
        buf.extend(chunk)
        while True:
            nl = buf.find(b"\n")
            if nl == -1:
                if len(buf) > 4096:
                    raise HTTPException(status_code=400, detail="Bad frame header")
                break  # header not complete yet
            parts = bytes(buf[:nl]).split()
            if len(parts) < 2 or parts[0] != b"EFSF":
                raise HTTPException(status_code=400, detail="Bad frame header")
            try:
                length = int(parts[1])
            except ValueError:
                raise HTTPException(status_code=400, detail="Bad frame length")
            if length <= 0 or length > MAX_FRAME_BYTES:
                raise HTTPException(status_code=413, detail="Frame too large")
            if len(buf) - (nl + 1) < length:
                break  # frame body not complete yet
            data = bytes(buf[nl + 1:nl + 1 + length])
            del buf[:nl + 1 + length]
            if data[:2] != b"\xff\xd8":  # JPEG start-of-image marker
                raise HTTPException(status_code=415, detail="Expected a JPEG frame")
            _store_frame(camera_id, data, _parse_packet_stats(parts))


def _fresh_frame(camera_id: str) -> Optional[bytes]:
    entry = _LATEST.get(camera_id)
    if entry is None:
        return None
    data, ts, _stats = entry
    if (time.time() - ts) > STALE_SECONDS:
        return None
    return data


@router.get("/{camera_id}/live/status")
def live_status(
    camera_id: str,
    _user: User = Depends(get_current_user),
) -> dict:
    """Is this camera streaming a preview, and at what pipeline rates? (owner-only)"""
    entry = _LATEST.get(camera_id)
    if entry is None:
        return {
            "online": False,
            "age_seconds": None,
            "capture_fps": None,
            "detect_fps": None,
            "profile": None,
            "source_fps": None,
            "frame_width": None,
            "frame_height": None,
            "live_quality": None,
            "cpu_temp_c": None,
            "queued": None,
        }
    age = round(time.time() - entry[1], 1)
    stats = entry[2] or {}
    return {
        "online": age <= STALE_SECONDS,
        "age_seconds": age,
        "capture_fps": stats.get("capture_fps"),
        "detect_fps": stats.get("detect_fps"),
        "profile": stats.get("profile"),
        "source_fps": stats.get("source_fps"),
        "frame_width": stats.get("frame_width"),
        "frame_height": stats.get("frame_height"),
        "live_quality": stats.get("live_quality"),
        "cpu_temp_c": stats.get("cpu_temp_c"),
        "queued": stats.get("queued"),
    }


@router.get("/{camera_id}/live")
def get_live_frame(
    camera_id: str,
    _user: User = Depends(get_current_user),
) -> Response:
    """The owner's console fetches the latest preview frame (owner-only)."""
    data = _fresh_frame(camera_id)
    if data is None:
        raise HTTPException(status_code=404, detail="No live preview for this camera")
    return Response(
        content=data, media_type="image/jpeg", headers={"Cache-Control": "no-store"}
    )


@router.get("/{camera_id}/live/stream")
async def stream_live_frames(
    request: Request,
    camera_id: str,
    _owner: str = Depends(require_owner),
) -> StreamingResponse:
    """MJPEG stream of a camera's live preview (owner-only).

    One held-open connection instead of the console re-requesting a frame
    every ~100ms: each new frame the edge pushes into `_LATEST` is written out
    as soon as it lands, so the console just decodes bytes as they arrive.

    Auth uses ``require_owner`` (not ``get_current_user``) so no DB connection
    is pinned for the - potentially very long - lifetime of the stream.
    """
    global _active_streams
    if _active_streams >= _MAX_CONCURRENT_STREAMS:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Too many live viewers; close another stream and retry.",
        )

    async def frames():
        global _active_streams
        _active_streams += 1
        try:
            last_ts = 0.0
            while not await request.is_disconnected():
                entry = _LATEST.get(camera_id)
                if entry is not None:
                    data, ts, _stats = entry
                    if ts != last_ts and (time.time() - ts) <= STALE_SECONDS:
                        last_ts = ts
                        yield (
                            b"--" + _MJPEG_BOUNDARY + b"\r\n"
                            b"Content-Type: image/jpeg\r\n"
                            b"Content-Length: " + str(len(data)).encode() + b"\r\n\r\n"
                            + data + b"\r\n"
                        )
                # Sleep until the camera pushes its next frame (or a short
                # timeout, so a vanished client is still noticed promptly).
                waiter = _FRAME_EVENTS.setdefault(camera_id, asyncio.Event())
                try:
                    await asyncio.wait_for(
                        waiter.wait(), timeout=_STREAM_IDLE_WAKE_SECONDS
                    )
                except asyncio.TimeoutError:
                    pass
        finally:
            _active_streams -= 1

    return StreamingResponse(
        frames(),
        media_type=f"multipart/x-mixed-replace; boundary={_MJPEG_BOUNDARY.decode()}",
        headers={"Cache-Control": "no-store"},
    )
