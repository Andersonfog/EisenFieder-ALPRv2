"""Vehicle-event ingest (from cameras) and search/export (for the owner console).

A "vehicle event" is one vehicle seen at an entrance, with everything the camera
could read about it: license plate, car make/color/type, how many people were
inside, and any company name on the side. Each event keeps ONE still image.
"""

from __future__ import annotations

import asyncio
import csv
import io
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import (
    APIRouter, Depends, File, Form, HTTPException, Query, Request, Response,
    UploadFile, status,
)
from fastapi.responses import StreamingResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..alerts import get_alert_dispatcher
from ..config import get_settings
from ..database import get_db
from ..models import Camera, User, VehicleEvent, WatchlistEntry
from ..plates import normalize_plate
from ..schemas import (
    IngestResult, LabelCount, SimilarVehicleOut, SimilarVehiclesOut, StatsOut,
    VehicleEventListOut, VehicleEventMetadata, VehicleEventOut,
)
from ..security import get_current_user, require_camera_auth, require_owner
from ..similarity import cosine
from ..storage import storage_singleton

router = APIRouter(prefix="/api/v1", tags=["vehicles"])

# --------------------------------------------------------------------------- #
# Change notification: the console's /vehicles/updates stream sleeps on this
# and ingest fires it after every commit, so the log updates the instant an
# event lands instead of on the next poll. Same one-shot broadcast pattern as
# the live-preview stream (single-process by design).
# --------------------------------------------------------------------------- #
_change_seq: int = 0
_change_event: Optional[asyncio.Event] = None


def _notify_change() -> None:
    global _change_seq, _change_event
    _change_seq += 1
    waiter, _change_event = _change_event, None
    if waiter is not None:
        waiter.set()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_dt(value: Optional[str]) -> datetime:
    if not value:
        return _utcnow()
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return _utcnow()


def _csv_safe(value) -> str:
    """Neutralize spreadsheet formula injection in exported CSV cells.

    Ingest fields (plate, company name, etc.) are attacker-influenced, so a
    value like ``=HYPERLINK(...)`` or ``+cmd`` would execute if the owner opens
    the CSV in Excel/Sheets. Prefix any cell that starts with a formula trigger
    with a single quote so the spreadsheet treats it as literal text.
    """
    s = "" if value is None else str(value)
    if s and s[0] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + s
    return s


# A stranger's car and a regular's car can look alike; only claim a returning
# vehicle BY APPEARANCE when the fingerprints match this strongly.
_APPEARANCE_MATCH_SCORE = 0.92


def _learn_visit(db: Session, *, event_uuid: str, plate_norm: str,
                 extra: Optional[dict]) -> Optional[dict]:
    """What the system has learned about this vehicle from past events.

    Identity first: the same normalized PLATE is the same vehicle, full stop.
    With no plate to go on, fall back to the side-profile appearance
    fingerprint — clearly labeled, because "looks the same" is a suggestion.
    Returns {"count": N, "first_seen": iso, "by": "plate"|"appearance"} or
    None for a first-time (or unmatchable) vehicle.
    """
    def _iso(dt) -> Optional[str]:
        return dt.isoformat() if dt else None

    if plate_norm:
        q = (db.query(VehicleEvent)
             .filter(VehicleEvent.plate_normalized == plate_norm,
                     VehicleEvent.id != event_uuid))
        prior = q.count()
        if prior:
            first = q.order_by(VehicleEvent.captured_at.asc()).first()
            return {"count": prior + 1, "first_seen": _iso(first.captured_at),
                    "by": "plate"}
        return None  # a plate we can trust says: first visit

    vec = (extra or {}).get("profile_vec")
    version = (extra or {}).get("profile_v")
    if not vec:
        return None
    candidates = (
        db.query(VehicleEvent)
        .filter(VehicleEvent.id != event_uuid, VehicleEvent.extra.isnot(None))
        .order_by(VehicleEvent.captured_at.desc())
        .limit(1000)
        .all()
    )
    matches = [c for c in candidates
               if (c.extra or {}).get("profile_v") == version
               and cosine(vec, (c.extra or {}).get("profile_vec"))
               >= _APPEARANCE_MATCH_SCORE]
    if not matches:
        return None
    first = min(matches, key=lambda c: c.captured_at)
    return {"count": len(matches) + 1, "first_seen": _iso(first.captured_at),
            "by": "appearance"}


def _check_watchlist(db: Session, plate_normalized: str) -> Optional[str]:
    """Return a flag reason if this plate is on the active watchlist."""
    if not plate_normalized:
        return None
    hit = (
        db.query(WatchlistEntry)
        .filter(
            WatchlistEntry.active.is_(True),
            WatchlistEntry.plate_normalized == plate_normalized,
        )
        .first()
    )
    if hit is None:
        return None
    return hit.label or hit.reason or "Watchlisted plate"


# --------------------------------------------------------------------------- #
# Ingest (camera -> backend). Idempotent on event_uuid.
# --------------------------------------------------------------------------- #
@router.post("/vehicles", response_model=IngestResult)
async def ingest_vehicle(
    response: Response,
    metadata: str = Form(...),
    image: Optional[UploadFile] = File(default=None),
    plate_image: Optional[UploadFile] = File(default=None),
    profile_image: Optional[UploadFile] = File(default=None),
    camera_id: str = Depends(require_camera_auth),
    db: Session = Depends(get_db),
) -> IngestResult:
    try:
        meta = VehicleEventMetadata.model_validate_json(metadata)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid metadata JSON: {exc}",
        )

    # A re-sent event_uuid from the SAME camera is an update-in-place: the edge
    # logs a provisional row the instant a vehicle is confirmed, then enriches
    # it (fused plate, direction, best still) when the pass ends. A different
    # camera reusing someone else's uuid is rejected as a duplicate.
    existing = db.get(VehicleEvent, meta.event_uuid)
    if existing is not None and existing.camera_id != camera_id:
        response.status_code = status.HTTP_409_CONFLICT
        return IngestResult(
            status="duplicate", id=existing.id,
            flagged=existing.flagged, flag_reason=existing.flag_reason,
        )

    # Upsert the reporting camera and refresh its heartbeat.
    camera = db.get(Camera, camera_id)
    if camera is None:
        if get_settings().is_production:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Camera not registered. Register it via the console first.",
            )
        camera = Camera(id=camera_id, name=camera_id)
        db.add(camera)
    camera.last_seen = _utcnow()
    camera.status = "online"

    # Safety net: honor this camera's excluded vehicle types even if the edge
    # unit is running stale settings (it should already filter these out itself).
    excluded = (camera.settings or {}).get("excluded_types") or []
    if meta.vehicle_type and meta.vehicle_type in excluded:
        db.commit()  # keep the heartbeat
        return IngestResult(status="ignored", id=meta.event_uuid)

    max_bytes = get_settings().max_upload_mb * 1024 * 1024

    async def _store(upload: Optional[UploadFile], suffix: str) -> Optional[str]:
        if upload is None:
            return None
        # Read in chunks so an oversized upload is rejected at the cap instead
        # of being pulled fully into memory first.
        chunks: list[bytes] = []
        received = 0
        while True:
            chunk = await upload.read(1024 * 1024)
            if not chunk:
                break
            received += len(chunk)
            if received > max_bytes:
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail=f"Image exceeds {get_settings().max_upload_mb} MB limit",
                )
            chunks.append(chunk)
        data = b"".join(chunks)
        if not data:
            return None
        if data[:2] != b"\xff\xd8":
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail="Image must be a JPEG (invalid SOI marker)",
            )
        return storage_singleton().save(f"{camera_id}/{meta.event_uuid}{suffix}.jpg", data)

    image_key = await _store(image, "")
    plate_image_key = await _store(plate_image, "_plate")
    profile_image_key = await _store(profile_image, "_side")

    plate_norm = normalize_plate(meta.plate_text)
    flag_reason = _check_watchlist(db, plate_norm)

    # Learn from history: has this vehicle been here before? (Plate match =
    # identity; otherwise the appearance fingerprint suggests a return.)
    extra = dict(meta.metadata or {})
    try:
        visit = _learn_visit(db, event_uuid=meta.event_uuid,
                             plate_norm=plate_norm, extra=extra)
    except Exception:  # learning must never break ingest
        visit = None
    if visit:
        extra["visit"] = visit
    merged_extra = extra or None

    if existing is not None:
        # Enrich the provisional row in place. captured_at stays the moment
        # the vehicle was FIRST seen, so the row keeps its spot in the log.
        was_flagged = existing.flagged
        existing.direction = meta.direction or "unknown"
        existing.plate_text = (meta.plate_text or None) and meta.plate_text.upper()
        existing.plate_normalized = plate_norm or None
        existing.plate_confidence = meta.plate_confidence
        existing.plate_region = meta.plate_region
        existing.vehicle_type = meta.vehicle_type
        existing.vehicle_make = meta.vehicle_make
        existing.vehicle_model = meta.vehicle_model
        existing.vehicle_color = meta.vehicle_color
        existing.occupant_count = meta.occupant_count
        existing.is_commercial = meta.is_commercial
        existing.company_name = meta.company_name
        existing.confidence = meta.confidence
        if image_key:
            existing.image_key = image_key
        if plate_image_key:
            existing.plate_image_key = plate_image_key
        if profile_image_key:
            existing.profile_image_key = profile_image_key
        existing.flagged = flag_reason is not None
        existing.flag_reason = flag_reason
        existing.pending = meta.pending
        existing.extra = merged_extra
        db.commit()
        event = existing
        newly_flagged = flag_reason is not None and not was_flagged
        result_status = "updated"
        response.status_code = status.HTTP_200_OK
    else:
        event = VehicleEvent(
            id=meta.event_uuid,
            camera_id=camera_id,
            captured_at=_parse_dt(meta.captured_at),
            direction=meta.direction or "unknown",
            plate_text=(meta.plate_text or None) and meta.plate_text.upper(),
            plate_normalized=plate_norm or None,
            plate_confidence=meta.plate_confidence,
            plate_region=meta.plate_region,
            vehicle_type=meta.vehicle_type,
            vehicle_make=meta.vehicle_make,
            vehicle_model=meta.vehicle_model,
            vehicle_color=meta.vehicle_color,
            occupant_count=meta.occupant_count,
            is_commercial=meta.is_commercial,
            company_name=meta.company_name,
            confidence=meta.confidence,
            image_key=image_key,
            plate_image_key=plate_image_key,
            profile_image_key=profile_image_key,
            flagged=flag_reason is not None,
            flag_reason=flag_reason,
            pending=meta.pending,
            extra=merged_extra,
        )
        db.add(event)
        db.commit()
        newly_flagged = flag_reason is not None
        result_status = "created"
        response.status_code = status.HTTP_201_CREATED

    # A watchlisted plate just arrived -> text the owner (best-effort). Only on
    # the FIRST hit for this event: the finalize update must not double-text.
    if newly_flagged:
        try:
            get_alert_dispatcher(get_settings()).send_watchlist_hit(
                plate=event.plate_text, reason=flag_reason, camera_id=camera_id,
                captured_at=event.captured_at.isoformat() if event.captured_at else "",
                make=event.vehicle_make, model=event.vehicle_model,
                color=event.vehicle_color, vehicle_type=event.vehicle_type,
            )
        except Exception:  # an alert must never break ingest
            pass

    # Tell every open console the log just changed (push beats polling).
    _notify_change()

    return IngestResult(
        status=result_status, id=event.id, flagged=event.flagged, flag_reason=event.flag_reason
    )


# --------------------------------------------------------------------------- #
# Search (owner console). All require a valid owner JWT.
# --------------------------------------------------------------------------- #
def _apply_filters(q, *, plate, camera_id, vehicle_type, vehicle_color, vehicle_make,
                   company, direction, is_commercial, flagged, since, until, min_confidence):
    if plate:
        q = q.filter(VehicleEvent.plate_normalized.like(f"%{normalize_plate(plate)}%"))
    if camera_id:
        q = q.filter(VehicleEvent.camera_id == camera_id)
    if vehicle_type:
        q = q.filter(VehicleEvent.vehicle_type == vehicle_type)
    if vehicle_color:
        q = q.filter(VehicleEvent.vehicle_color == vehicle_color)
    if vehicle_make:
        q = q.filter(VehicleEvent.vehicle_make.ilike(f"%{vehicle_make}%"))
    if company:
        q = q.filter(VehicleEvent.company_name.ilike(f"%{company}%"))
    if direction:
        q = q.filter(VehicleEvent.direction == direction)
    if is_commercial is not None:
        q = q.filter(VehicleEvent.is_commercial.is_(is_commercial))
    if flagged is not None:
        q = q.filter(VehicleEvent.flagged.is_(flagged))
    if min_confidence is not None:
        q = q.filter(VehicleEvent.confidence >= min_confidence)
    if since:
        q = q.filter(VehicleEvent.captured_at >= _parse_dt(since))
    if until:
        q = q.filter(VehicleEvent.captured_at <= _parse_dt(until))
    return q


@router.get("/vehicles", response_model=VehicleEventListOut)
def list_vehicles(
    plate: Optional[str] = Query(default=None, description="Partial plate match"),
    camera_id: Optional[str] = None,
    vehicle_type: Optional[str] = None,
    vehicle_color: Optional[str] = None,
    vehicle_make: Optional[str] = None,
    company: Optional[str] = Query(default=None, description="Partial company-name match"),
    direction: Optional[str] = None,
    is_commercial: Optional[bool] = None,
    flagged: Optional[bool] = None,
    since: Optional[str] = Query(default=None, description="ISO datetime lower bound"),
    until: Optional[str] = Query(default=None, description="ISO datetime upper bound"),
    min_confidence: Optional[float] = None,
    limit: int = Query(default=50, le=500),
    offset: int = 0,
    _user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> VehicleEventListOut:
    q = _apply_filters(
        db.query(VehicleEvent), plate=plate, camera_id=camera_id, vehicle_type=vehicle_type,
        vehicle_color=vehicle_color, vehicle_make=vehicle_make, company=company,
        direction=direction, is_commercial=is_commercial, flagged=flagged,
        since=since, until=until, min_confidence=min_confidence,
    )
    total = q.count()
    items = q.order_by(VehicleEvent.captured_at.desc()).offset(offset).limit(limit).all()
    return VehicleEventListOut(total=total, items=items)


@router.get("/vehicles.csv")
def export_vehicles_csv(
    plate: Optional[str] = None,
    camera_id: Optional[str] = None,
    vehicle_type: Optional[str] = None,
    vehicle_color: Optional[str] = None,
    vehicle_make: Optional[str] = None,
    company: Optional[str] = None,
    direction: Optional[str] = None,
    is_commercial: Optional[bool] = None,
    flagged: Optional[bool] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
    min_confidence: Optional[float] = None,
    _user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """Download the (filtered) vehicle log as a CSV for records/reporting."""
    q = _apply_filters(
        db.query(VehicleEvent), plate=plate, camera_id=camera_id, vehicle_type=vehicle_type,
        vehicle_color=vehicle_color, vehicle_make=vehicle_make, company=company,
        direction=direction, is_commercial=is_commercial, flagged=flagged,
        since=since, until=until, min_confidence=min_confidence,
    )
    rows = q.order_by(VehicleEvent.captured_at.desc()).limit(10000).all()

    def generate():
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow([
            "event_uuid", "camera_id", "captured_at", "direction", "plate", "plate_region",
            "vehicle_type", "make", "model", "color", "occupants", "is_commercial", "company",
            "confidence", "flagged", "flag_reason",
        ])
        yield buf.getvalue()
        buf.seek(0); buf.truncate(0)
        for e in rows:
            writer.writerow([
                _csv_safe(e.id), _csv_safe(e.camera_id),
                e.captured_at.isoformat() if e.captured_at else "",
                _csv_safe(e.direction), _csv_safe(e.plate_text or ""),
                _csv_safe(e.plate_region or ""),
                _csv_safe(e.vehicle_type or ""), _csv_safe(e.vehicle_make or ""),
                _csv_safe(e.vehicle_model or ""), _csv_safe(e.vehicle_color or ""),
                e.occupant_count if e.occupant_count is not None else "",
                "yes" if e.is_commercial else "no", _csv_safe(e.company_name or ""),
                f"{e.confidence:.3f}" if e.confidence is not None else "",
                "yes" if e.flagged else "no", _csv_safe(e.flag_reason or ""),
            ])
            yield buf.getvalue()
            buf.seek(0); buf.truncate(0)

    headers = {"Content-Disposition": "attachment; filename=eisenfieder_vehicles.csv"}
    return StreamingResponse(generate(), media_type="text/csv", headers=headers)


@router.get("/vehicles/updates")
async def vehicle_updates(
    request: Request,
    limit: Optional[int] = Query(default=None, ge=1, le=1000,
                                 description="Close after N data messages "
                                             "(diagnostics/tests; default: stream forever)"),
    _owner: str = Depends(require_owner),
) -> StreamingResponse:
    """Server-sent events: one ``data:`` line every time the vehicle log
    changes (owner-only). The console holds this open and re-fetches the list
    the moment a ping arrives — instant updates without hammering the API.

    NOTE: registered before ``/vehicles/{event_id}`` so "updates" is never
    treated as an event id. Auth uses ``require_owner`` so no DB connection is
    pinned for the lifetime of the stream (same pattern as the live stream).
    """

    async def gen():
        global _change_event
        last = _change_seq
        # First byte immediately, so the client knows it's connected.
        yield f"data: {last}\n\n".encode()
        sent = 1
        while (limit is None or sent < limit) and not await request.is_disconnected():
            if _change_seq != last:
                last = _change_seq
                yield f"data: {last}\n\n".encode()
                sent += 1
                continue
            if _change_event is None:
                _change_event = asyncio.Event()
            waiter = _change_event
            try:
                # Wake on the next change, or every 15s to send a keep-alive
                # comment (also lets us notice a vanished client).
                await asyncio.wait_for(waiter.wait(), timeout=15.0)
            except asyncio.TimeoutError:
                yield b": ping\n\n"

    return StreamingResponse(
        gen(), media_type="text/event-stream", headers={"Cache-Control": "no-store"}
    )


@router.get("/vehicles/{event_id}", response_model=VehicleEventOut)
def get_vehicle(
    event_id: str,
    _user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> VehicleEvent:
    event = db.get(VehicleEvent, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Vehicle event not found")
    return event


@router.get("/vehicles/{event_id}/similar", response_model=SimilarVehiclesOut)
def similar_vehicles(
    event_id: str,
    limit: int = Query(default=6, ge=1, le=24),
    min_score: float = Query(default=0.60, ge=0.0, le=1.0),
    _user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SimilarVehiclesOut:
    """Past sightings that LOOK like this vehicle (owner-only).

    Compares the side-profile appearance fingerprints the edge unit stores
    with each event (colour + shape + geometry — see edge profiles.py). It's
    an appearance suggestion for the owner ("possibly the same car, 87%"),
    useful when a plate wasn't readable; it is never an identity claim.
    """
    event = db.get(VehicleEvent, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Vehicle event not found")
    vec = (event.extra or {}).get("profile_vec")
    version = (event.extra or {}).get("profile_v")
    if not vec:
        return SimilarVehiclesOut(items=[])

    # Fingerprints live in JSON, so score the most recent slice in Python —
    # bounded, and plenty for a single-business event history.
    candidates = (
        db.query(VehicleEvent)
        .filter(VehicleEvent.id != event_id, VehicleEvent.extra.isnot(None))
        .order_by(VehicleEvent.captured_at.desc())
        .limit(2000)
        .all()
    )
    scored: list[tuple[float, VehicleEvent]] = []
    for cand in candidates:
        extra = cand.extra or {}
        if extra.get("profile_v") != version:
            continue  # different fingerprint versions must not be compared
        score = cosine(vec, extra.get("profile_vec"))
        if score >= min_score:
            scored.append((score, cand))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return SimilarVehiclesOut(
        items=[SimilarVehicleOut(score=round(s, 4), event=e) for s, e in scored[:limit]]
    )


@router.get("/stats", response_model=StatsOut)
def stats(
    _user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StatsOut:
    total_vehicles = db.query(func.count(VehicleEvent.id)).scalar() or 0
    total_cameras = db.query(func.count(Camera.id)).scalar() or 0
    since = _utcnow() - timedelta(hours=24)
    last_24h = (
        db.query(func.count(VehicleEvent.id))
        .filter(VehicleEvent.captured_at >= since).scalar() or 0
    )
    flagged_total = (
        db.query(func.count(VehicleEvent.id))
        .filter(VehicleEvent.flagged.is_(True)).scalar() or 0
    )
    commercial_total = (
        db.query(func.count(VehicleEvent.id))
        .filter(VehicleEvent.is_commercial.is_(True)).scalar() or 0
    )
    type_rows = (
        db.query(VehicleEvent.vehicle_type, func.count(VehicleEvent.id))
        .group_by(VehicleEvent.vehicle_type)
        .order_by(func.count(VehicleEvent.id).desc())
        .all()
    )
    dir_rows = (
        db.query(VehicleEvent.direction, func.count(VehicleEvent.id))
        .group_by(VehicleEvent.direction)
        .order_by(func.count(VehicleEvent.id).desc())
        .all()
    )
    return StatsOut(
        total_vehicles=total_vehicles,
        total_cameras=total_cameras,
        vehicles_last_24h=last_24h,
        flagged_total=flagged_total,
        commercial_total=commercial_total,
        by_type=[LabelCount(label=t or "unknown", count=c) for t, c in type_rows],
        by_direction=[LabelCount(label=d or "unknown", count=c) for d, c in dir_rows],
    )
