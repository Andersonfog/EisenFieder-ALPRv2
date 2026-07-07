"""Pydantic request/response schemas."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator


def _utc_iso(value: Optional[datetime]) -> Optional[str]:
    """Serialize a datetime as UTC ISO-8601 with an explicit offset.

    SQLite returns naive datetimes; without a tz marker the browser would treat
    them as local time. We persist UTC, so assume UTC when tzinfo is missing.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


# --- Auth ---
class LoginIn(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(max_length=256)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    email: str


# --- Vehicle events ---
class VehicleEventMetadata(BaseModel):
    """The JSON the edge uploader sends in the multipart `metadata` field."""

    # Both are used to build the on-disk still key (f"{camera_id}/{event_uuid}.jpg"),
    # so they are restricted to a path-safe charset (no "/", no ".."). uuid4 and
    # normal serials match; a traversal payload is rejected with 422.
    event_uuid: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    camera_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    captured_at: Optional[str] = Field(default=None, max_length=40)
    direction: str = Field(default="unknown", max_length=16)
    plate_text: Optional[str] = Field(default=None, max_length=32)
    plate_confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    plate_region: Optional[str] = Field(default=None, max_length=32)
    vehicle_type: Optional[str] = Field(default=None, max_length=32)
    vehicle_make: Optional[str] = Field(default=None, max_length=64)
    vehicle_model: Optional[str] = Field(default=None, max_length=64)
    vehicle_color: Optional[str] = Field(default=None, max_length=32)
    occupant_count: Optional[int] = Field(default=None, ge=0, le=20)
    is_commercial: bool = False
    company_name: Optional[str] = Field(default=None, max_length=128)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    # True = the vehicle is still in view; the event will be enriched shortly.
    pending: bool = False
    metadata: Optional[dict[str, Any]] = None


class VehicleEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    camera_id: str
    captured_at: datetime
    direction: str
    plate_text: Optional[str]
    plate_confidence: Optional[float]
    plate_region: Optional[str]
    vehicle_type: Optional[str]
    vehicle_make: Optional[str]
    vehicle_model: Optional[str]
    vehicle_color: Optional[str]
    occupant_count: Optional[int]
    is_commercial: bool
    company_name: Optional[str]
    confidence: float
    image_url: Optional[str]
    plate_image_url: Optional[str]
    # Best side-view crop of the pass (the vehicle's visual "profile shot").
    profile_image_url: Optional[str] = None
    flagged: bool
    flag_reason: Optional[str]
    pending: bool = False
    # Learned visit history: {"count": N, "first_seen": iso, "by": "plate" |
    # "appearance"}. None until the vehicle has been seen more than once.
    visit: Optional[dict] = None
    created_at: datetime

    @field_serializer("captured_at", "created_at")
    def _ser_dt(self, v: datetime) -> Optional[str]:
        return _utc_iso(v)


class VehicleEventListOut(BaseModel):
    total: int
    items: list[VehicleEventOut]


class IngestResult(BaseModel):
    status: str
    id: str
    flagged: bool = False
    flag_reason: Optional[str] = None


class SimilarVehicleOut(BaseModel):
    """A past event whose side-profile fingerprint LOOKS like the queried one.

    ``score`` is appearance similarity (0-1), not identity — plates do identity.
    """

    score: float
    event: VehicleEventOut


class SimilarVehiclesOut(BaseModel):
    items: list[SimilarVehicleOut]


# --- Cameras ---
class CameraSettings(BaseModel):
    """Per-camera settings the edge unit pulls and enforces."""

    # Vehicle types this camera should ignore (e.g. ["motorcycle"]).
    excluded_types: list[str] = Field(default_factory=list)
    # Override the detection confidence threshold for this camera (None = default).
    min_confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    # What to try to capture per vehicle.
    capture_plate: bool = True
    capture_occupants: bool = True
    capture_company: bool = True
    # Send the owner an alert when a watchlisted plate is seen.
    alerts_enabled: bool = True
    # ALPR capture/profile controls. The edge applies these on pull/restart.
    quality_profile: str = Field(default="sharp_read", max_length=32)
    enhance_plate: bool = True
    lock_exposure: bool = True
    edge_only: bool = True


class CameraCreate(BaseModel):
    """Owner registers a camera by a serial number they choose."""

    serial_number: str = Field(min_length=1, max_length=64)
    name: Optional[str] = Field(default=None, max_length=255)
    location: Optional[str] = Field(default=None, max_length=255)


class CameraOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    location: str
    status: str
    has_token: bool = False
    settings: CameraSettings = Field(default_factory=CameraSettings)
    last_seen: Optional[datetime]
    created_at: datetime

    @field_validator("settings", mode="before")
    @classmethod
    def _settings_default(cls, v):
        # The DB column may be NULL; treat that as default settings.
        return v or {}

    @field_serializer("last_seen", "created_at")
    def _ser_dt(self, v: Optional[datetime]) -> Optional[str]:
        return _utc_iso(v)


class CameraRegistered(BaseModel):
    """Returned once on registration — includes the pairing token (shown once)."""

    id: str                 # the serial number
    name: str
    api_token: str          # copy into the unit's config; not retrievable later
    env_snippet: str        # convenience for the Pi setup


class CameraSettingsUpdate(CameraSettings):
    """Body for PUT /cameras/{id}/settings (same shape as CameraSettings)."""


# --- Watchlist ---
class WatchlistCreate(BaseModel):
    plate_text: str = Field(min_length=1, max_length=32)
    label: Optional[str] = Field(default=None, max_length=128)
    reason: Optional[str] = Field(default=None, max_length=255)


class WatchlistOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    plate_text: str
    plate_normalized: str
    label: str
    reason: Optional[str]
    active: bool
    created_at: datetime

    @field_serializer("created_at")
    def _ser_dt(self, v: datetime) -> Optional[str]:
        return _utc_iso(v)


# --- Stats (console overview) ---
class LabelCount(BaseModel):
    label: str
    count: int


class StatsOut(BaseModel):
    total_vehicles: int
    total_cameras: int
    vehicles_last_24h: int
    flagged_total: int
    commercial_total: int
    by_type: list[LabelCount]
    by_direction: list[LabelCount]


# --- Settings (console) ---
class SettingsOut(BaseModel):
    # IANA timezone name used to display Insights in local time (e.g.
    # "America/New_York"). "UTC" if never changed.
    timezone: str
    # A short friendly list for the console dropdown (the API accepts any valid
    # IANA name, not just these).
    common_timezones: list[str] = Field(default_factory=list)


class SettingsUpdate(BaseModel):
    timezone: str = Field(min_length=1, max_length=64)


# --- Analytics / insights (console) ---
class HourCount(BaseModel):
    hour: int          # 0..23 (in the business's display timezone)
    count: int


class WeekdayCount(BaseModel):
    weekday: int       # 0=Mon .. 6=Sun
    label: str
    count: int


class CompanyCount(BaseModel):
    name: str
    count: int


class RepeatVisitor(BaseModel):
    plate: str
    visits: int
    first_seen: datetime
    last_seen: datetime

    @field_serializer("first_seen", "last_seen")
    def _ser_dt(self, v: datetime) -> Optional[str]:
        return _utc_iso(v)


class AnalyticsOut(BaseModel):
    range_days: int
    timezone: str                    # IANA name the hour/day buckets are in
    total_events: int
    unique_plates: int
    returning_vehicles: int          # distinct plates seen 2+ times in range
    commercial_count: int
    commercial_ratio: float          # 0..1
    busiest_hour: Optional[int]      # 0..23 (display timezone), None if no data
    busiest_weekday: Optional[str]   # e.g. "Fri", None if no data
    by_hour: list[HourCount]
    by_weekday: list[WeekdayCount]
    top_companies: list[CompanyCount]
    repeat_visitors: list[RepeatVisitor]
