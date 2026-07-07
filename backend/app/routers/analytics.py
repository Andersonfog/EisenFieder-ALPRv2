"""Business insights derived from the vehicle log (owner console).

Turns the raw event log into the things a business owner actually wants to know:
*when* traffic peaks (hour of day / day of week), *who keeps coming back*
(plates seen more than once), and *which commercial fleets* show up most.

Everything here is computed from real captured events — no estimates, no
fabricated data. Timestamps are stored in UTC; the hour-of-day and day-of-week
buckets are converted to the business's display timezone (set in the console)
so "busiest hour" reads as the owner's local clock, not UTC.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User, VehicleEvent
from ..schemas import (
    AnalyticsOut, CompanyCount, HourCount, RepeatVisitor, WeekdayCount,
)
from ..security import get_current_user
from ..settings_store import get_display_tz, get_timezone_name

router = APIRouter(prefix="/api/v1/analytics", tags=["analytics"])

_WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


@router.get("", response_model=AnalyticsOut)
def analytics(
    days: int = Query(default=30, ge=1, le=365, description="Look-back window in days"),
    _user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AnalyticsOut:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    in_range = VehicleEvent.captured_at >= since

    tz_name = get_timezone_name(db)
    display_tz = get_display_tz(db)

    total = db.query(func.count(VehicleEvent.id)).filter(in_range).scalar() or 0

    # Time-of-day / day-of-week buckets. Bucketing in Python keeps this portable
    # across SQLite and Postgres (no DB-specific date functions) and lets us
    # convert each timestamp into the owner's local timezone first. SQLite gives
    # back naive datetimes, so we treat them as UTC (that's how they're stored).
    hours = [0] * 24
    weekdays = [0] * 7
    for (cap,) in db.query(VehicleEvent.captured_at).filter(in_range).all():
        if cap is None:
            continue
        if cap.tzinfo is None:
            cap = cap.replace(tzinfo=timezone.utc)
        local = cap.astimezone(display_tz)
        hours[local.hour] += 1
        weekdays[local.weekday()] += 1

    by_hour = [HourCount(hour=h, count=c) for h, c in enumerate(hours)]
    by_weekday = [
        WeekdayCount(weekday=i, label=_WEEKDAYS[i], count=c)
        for i, c in enumerate(weekdays)
    ]
    busiest_hour = max(range(24), key=lambda h: hours[h]) if total else None
    busiest_wd = max(range(7), key=lambda i: weekdays[i]) if total else None

    commercial = (
        db.query(func.count(VehicleEvent.id))
        .filter(in_range, VehicleEvent.is_commercial.is_(True))
        .scalar() or 0
    )

    company_rows = (
        db.query(VehicleEvent.company_name, func.count(VehicleEvent.id))
        .filter(in_range, VehicleEvent.is_commercial.is_(True),
                VehicleEvent.company_name.isnot(None))
        .group_by(VehicleEvent.company_name)
        .order_by(func.count(VehicleEvent.id).desc())
        .limit(8)
        .all()
    )
    top_companies = [CompanyCount(name=n, count=c) for n, c in company_rows if n]

    plated = in_range & VehicleEvent.plate_normalized.isnot(None) & (
        VehicleEvent.plate_normalized != ""
    )
    repeat_rows = (
        db.query(
            VehicleEvent.plate_normalized,
            func.min(VehicleEvent.plate_text),
            func.count(VehicleEvent.id),
            func.min(VehicleEvent.captured_at),
            func.max(VehicleEvent.captured_at),
        )
        .filter(plated)
        .group_by(VehicleEvent.plate_normalized)
        .having(func.count(VehicleEvent.id) >= 2)
        .order_by(func.count(VehicleEvent.id).desc())
        .limit(10)
        .all()
    )
    repeat_visitors = [
        RepeatVisitor(plate=pt or pn, visits=c, first_seen=fs, last_seen=ls)
        for pn, pt, c, fs, ls in repeat_rows
    ]

    returning_vehicles = (
        db.query(VehicleEvent.plate_normalized)
        .filter(plated)
        .group_by(VehicleEvent.plate_normalized)
        .having(func.count(VehicleEvent.id) >= 2)
        .count()
    )
    unique_plates = (
        db.query(func.count(func.distinct(VehicleEvent.plate_normalized)))
        .filter(plated)
        .scalar() or 0
    )

    return AnalyticsOut(
        range_days=days,
        timezone=tz_name,
        total_events=total,
        unique_plates=unique_plates,
        returning_vehicles=returning_vehicles,
        commercial_count=commercial,
        commercial_ratio=round(commercial / total, 3) if total else 0.0,
        busiest_hour=busiest_hour,
        busiest_weekday=_WEEKDAYS[busiest_wd] if busiest_wd is not None else None,
        by_hour=by_hour,
        by_weekday=by_weekday,
        top_companies=top_companies,
        repeat_visitors=repeat_visitors,
    )
