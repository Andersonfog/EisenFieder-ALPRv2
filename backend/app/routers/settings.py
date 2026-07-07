"""Business-wide settings the owner manages in the console.

Currently just the display timezone for Insights. Owner-only, like everything
else in this single-tenant product.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User
from ..schemas import SettingsOut, SettingsUpdate
from ..security import get_current_user
from ..settings_store import (
    COMMON_TIMEZONES, SETTING_TIMEZONE, get_timezone_name, is_valid_timezone,
    set_setting,
)

router = APIRouter(prefix="/api/v1/settings", tags=["settings"])


@router.get("", response_model=SettingsOut)
def read_settings(
    _user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SettingsOut:
    return SettingsOut(
        timezone=get_timezone_name(db),
        common_timezones=COMMON_TIMEZONES,
    )


@router.put("", response_model=SettingsOut)
def update_settings(
    body: SettingsUpdate,
    _user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SettingsOut:
    tz = body.timezone.strip()
    if not is_valid_timezone(tz):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown timezone '{tz}'. Use an IANA name like 'America/New_York'.",
        )
    set_setting(db, SETTING_TIMEZONE, tz)
    return SettingsOut(timezone=tz, common_timezones=COMMON_TIMEZONES)
