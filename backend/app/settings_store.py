"""Business-wide settings the owner can change in the console.

Right now this holds a single setting — the display timezone for Insights — but
it's built as a generic key/value store so future toggles don't need their own
table or migration.

The timezone is stored as an IANA name (e.g. ``America/New_York``). We validate
it against the system's timezone database (``zoneinfo``) before saving, and fall
back to UTC anywhere a stored value has somehow gone bad, so analytics can never
crash on a typo.
"""

from __future__ import annotations

from datetime import tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

from sqlalchemy.orm import Session

from .config import get_settings
from .models import AppSetting

SETTING_TIMEZONE = "timezone"

# A short, friendly list surfaced to the console dropdown. The API still accepts
# *any* valid IANA name, but these cover the common cases for a US business
# without overwhelming a non-technical owner with 500 options.
COMMON_TIMEZONES = [
    "UTC",
    "America/New_York",
    "America/Chicago",
    "America/Denver",
    "America/Phoenix",
    "America/Los_Angeles",
    "America/Anchorage",
    "Pacific/Honolulu",
    "America/Toronto",
    "America/Mexico_City",
    "Europe/London",
    "Europe/Paris",
    "Europe/Berlin",
    "Australia/Sydney",
]


def is_valid_timezone(name: str) -> bool:
    """True if ``name`` is a timezone the system can actually resolve."""
    if not name:
        return False
    try:
        ZoneInfo(name)
        return True
    except (ZoneInfoNotFoundError, ValueError, KeyError, OSError):
        return False


def get_setting(db: Session, key: str) -> str | None:
    row = db.get(AppSetting, key)
    return row.value if row else None


def set_setting(db: Session, key: str, value: str) -> None:
    row = db.get(AppSetting, key)
    if row is None:
        db.add(AppSetting(key=key, value=value))
    else:
        row.value = value
    db.commit()


def get_timezone_name(db: Session) -> str:
    """The effective display timezone: DB override → config default → UTC.

    Always returns a name that actually resolves, so callers can trust it.
    """
    stored = get_setting(db, SETTING_TIMEZONE)
    if stored and is_valid_timezone(stored):
        return stored
    fallback = get_settings().business_timezone
    return fallback if is_valid_timezone(fallback) else "UTC"


def get_display_tz(db: Session) -> tzinfo:
    """The resolved :class:`tzinfo` for bucketing analytics into local time."""
    try:
        return ZoneInfo(get_timezone_name(db))
    except (ZoneInfoNotFoundError, ValueError, KeyError, OSError):
        return ZoneInfo("UTC")


def all_timezone_names() -> list[str]:
    """Every IANA name the system knows (for validation / an advanced picker)."""
    return sorted(available_timezones())
