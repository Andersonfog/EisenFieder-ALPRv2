"""Delete captured vehicle events (and their stored images) for a clean start.

Keeps the owner login, cameras, and watchlist — only the vehicle log is cleared.
Use this before a real prototype run so the log shows only what your camera
actually captures (not the demo/seed data).

    cd backend
    python -m scripts.clear_events          # asks to confirm
    python -m scripts.clear_events --yes     # no prompt (scripted)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal  # noqa: E402
from app.models import VehicleEvent  # noqa: E402
from app.storage import storage_singleton  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Clear the vehicle event log.")
    parser.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        total = db.query(VehicleEvent).count()
        if total == 0:
            print("No vehicle events to clear.")
            return
        if not args.yes:
            resp = input(f"Delete ALL {total} vehicle events? (cameras + watchlist kept) [y/N] ")
            if resp.strip().lower() not in ("y", "yes"):
                print("Cancelled.")
                return

        storage = storage_singleton()
        removed_files = 0
        for event in db.query(VehicleEvent).all():
            for key in (event.image_key, event.plate_image_key):
                if not key:
                    continue
                path = storage.path_for(key)
                if path is not None:
                    try:
                        path.unlink()
                        removed_files += 1
                    except OSError:
                        pass

        db.query(VehicleEvent).delete()
        db.commit()
        print(f"Cleared {total} vehicle events and removed {removed_files} image files.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
