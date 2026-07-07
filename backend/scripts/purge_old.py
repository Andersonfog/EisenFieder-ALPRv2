"""Delete vehicle records (and their images) older than DATA_RETENTION_DAYS.

    cd backend
    python -m scripts.purge_old            # uses DATA_RETENTION_DAYS from env/.env
    python -m scripts.purge_old --days 30  # override

A privacy/housekeeping tool: surveillance data shouldn't pile up forever. With
DATA_RETENTION_DAYS=0 (the default) nothing is purged.
"""

from __future__ import annotations

import argparse
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.models import VehicleEvent  # noqa: E402
from app.routers.vehicles import _utcnow  # noqa: E402
from app.storage import storage_singleton  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=None, help="Override DATA_RETENTION_DAYS")
    args = ap.parse_args()

    days = args.days if args.days is not None else get_settings().data_retention_days
    if days <= 0:
        print("Retention is 0 (keep forever) - nothing purged. Pass --days N to override.")
        return

    cutoff = _utcnow() - timedelta(days=days)
    storage = storage_singleton()
    db = SessionLocal()
    deleted = 0
    try:
        old = db.query(VehicleEvent).filter(VehicleEvent.captured_at < cutoff).all()
        for e in old:
            for key in (e.image_key, e.plate_image_key):
                p = storage.path_for(key) if key else None
                if p is not None:
                    try:
                        p.unlink()
                    except OSError:
                        pass
            db.delete(e)
            deleted += 1
        db.commit()
        print(f"Purged {deleted} vehicle records older than {days} days (before {cutoff.date()}).")
    finally:
        db.close()


if __name__ == "__main__":
    main()
