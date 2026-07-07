"""Plate watchlist — plates the owner wants flagged on sight.

When a camera reports a plate that matches an active entry, the vehicle event is
saved with ``flagged=True`` so it stands out in the console.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User, WatchlistEntry
from ..plates import normalize_plate
from ..schemas import WatchlistCreate, WatchlistOut
from ..security import get_current_user

router = APIRouter(prefix="/api/v1/watchlist", tags=["watchlist"])


@router.get("", response_model=list[WatchlistOut])
def list_watchlist(
    _user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[WatchlistEntry]:
    return db.query(WatchlistEntry).order_by(WatchlistEntry.created_at.desc()).all()


@router.post("", response_model=WatchlistOut, status_code=status.HTTP_201_CREATED)
def add_watchlist(
    body: WatchlistCreate,
    _user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WatchlistEntry:
    normalized = normalize_plate(body.plate_text)
    if not normalized:
        raise HTTPException(status_code=422, detail="Plate must contain letters or digits")
    entry = WatchlistEntry(
        plate_text=body.plate_text.upper(),
        plate_normalized=normalized,
        label=(body.label or "").strip(),
        reason=body.reason,
        active=True,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


@router.patch("/{entry_id}", response_model=WatchlistOut)
def toggle_watchlist(
    entry_id: int,
    active: bool,
    _user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WatchlistEntry:
    entry = db.get(WatchlistEntry, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Watchlist entry not found")
    entry.active = active
    db.commit()
    db.refresh(entry)
    return entry


@router.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_watchlist(
    entry_id: int,
    _user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    entry = db.get(WatchlistEntry, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Watchlist entry not found")
    db.delete(entry)
    db.commit()
