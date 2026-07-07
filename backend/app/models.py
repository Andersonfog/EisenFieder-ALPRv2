"""Database models: the business owner, entrance cameras, vehicle events, and
the plate watchlist.

NOTE: SQLAlchemy reserves the attribute name ``metadata`` on declarative classes,
so the free-form event metadata is stored on the ``extra`` attribute (column
``meta``).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    """The business owner — the only human who can log into the console."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class Camera(Base):
    """An entrance-mounted surveillance camera."""

    __tablename__ = "cameras"

    # The owner-chosen serial number IS the camera id (X-Camera-Id on reports).
    id: Mapped[str] = mapped_column(String(64), primary_key=True)   # e.g. EFS-SN-00231
    name: Mapped[str] = mapped_column(String(255), default="")
    location: Mapped[str] = mapped_column(String(255), default="")  # e.g. "Front entrance"
    # Per-camera pairing secret. When set, the unit must present it as a bearer
    # token to ingest events. Generated at registration, shown once.
    api_token: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="registered")
    last_seen: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    # Per-camera settings (excluded vehicle types, thresholds, capture toggles).
    # The edge unit pulls these and applies them locally. JSON keeps it flexible.
    settings: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    events: Mapped[list["VehicleEvent"]] = relationship(back_populates="camera")


class VehicleEvent(Base):
    """A single vehicle seen at an entrance: who/what was captured + one still."""

    __tablename__ = "vehicle_events"
    __table_args__ = (
        # "This camera's events, newest first" — the log page's hottest query.
        Index("ix_events_camera_captured", "camera_id", "captured_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)   # event_uuid (idempotent)
    camera_id: Mapped[str] = mapped_column(ForeignKey("cameras.id"), index=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

    # Direction of travel through the entrance: "in", "out" or "unknown".
    direction: Mapped[str] = mapped_column(String(16), default="unknown", index=True)

    # License plate.
    plate_text: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, index=True)
    plate_normalized: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, index=True)
    plate_confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    plate_region: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)  # state/region

    # The vehicle itself.
    vehicle_type: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, index=True)  # car/suv/truck/van...
    vehicle_make: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    vehicle_model: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    vehicle_color: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, index=True)

    # People in the car.
    occupant_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Commercial branding read off the side of the vehicle (if any).
    is_commercial: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    company_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)

    # Overall detection confidence for the vehicle (0..1).
    confidence: Mapped[float] = mapped_column(Float, default=0.0)

    # Captured stills (stored as keys; served only via authenticated /media).
    image_key: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    plate_image_key: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    # Best SIDE-view crop of the pass (the vehicle's visual "profile shot");
    # its appearance fingerprint lives in extra["profile_vec"].
    profile_image_key: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)

    # Watchlist hit.
    flagged: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    flag_reason: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # True while the vehicle is still in view: the event was logged the moment
    # the vehicle was confirmed, and will be enriched (fused plate, direction,
    # best still) when the pass ends. The console shows these as live rows.
    pending: Mapped[bool] = mapped_column(Boolean, default=False)

    extra: Mapped[Optional[dict]] = mapped_column("meta", JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    camera: Mapped["Camera"] = relationship(back_populates="events")

    # The console never receives raw disk paths — only authenticated URLs.
    # The ?v= suffix versions the URL: the still is replaced in place when a
    # pending event finalizes, and the changed URL busts the browser's
    # immutable media cache exactly then.
    @property
    def image_url(self) -> Optional[str]:
        if not self.image_key:
            return None
        return f"/api/v1/media/{self.image_key}?v={'p' if self.pending else 'f'}"

    @property
    def plate_image_url(self) -> Optional[str]:
        if not self.plate_image_key:
            return None
        return f"/api/v1/media/{self.plate_image_key}?v={'p' if self.pending else 'f'}"

    @property
    def profile_image_url(self) -> Optional[str]:
        if not self.profile_image_key:
            return None
        return f"/api/v1/media/{self.profile_image_key}?v={'p' if self.pending else 'f'}"

    @property
    def visit(self) -> Optional[dict]:
        """What the system has LEARNED about this vehicle's visit history:
        {"count": N, "first_seen": iso, "by": "plate"|"appearance"} — set at
        ingest by matching the plate (identity) or, failing that, the
        side-profile fingerprint (appearance suggestion)."""
        return (self.extra or {}).get("visit")


class AppSetting(Base):
    """A single business-wide setting, stored as a key/value pair.

    Single-tenant, so one row per key is enough. Used for things the owner tweaks
    in the console that must survive a restart (e.g. the display timezone for
    Insights). Kept as a generic table so new settings don't need a migration.
    """

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


class WatchlistEntry(Base):
    """A plate the owner wants flagged on sight (banned customer, BOLO, etc.)."""

    __tablename__ = "watchlist"

    id: Mapped[int] = mapped_column(primary_key=True)
    plate_text: Mapped[str] = mapped_column(String(32))
    plate_normalized: Mapped[str] = mapped_column(String(32), index=True)
    label: Mapped[str] = mapped_column(String(128), default="")
    reason: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
