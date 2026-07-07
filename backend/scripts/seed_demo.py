"""Seed a demo camera and a batch of realistic vehicle events.

    cd backend
    python -m scripts.seed_demo

Useful for clicking around the console before any real camera is connected.
"""

from __future__ import annotations

import random
import sys
import uuid
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.models import Camera, VehicleEvent, WatchlistEntry  # noqa: E402
from app.plates import normalize_plate  # noqa: E402
from app.routers.vehicles import _utcnow  # noqa: E402

CAMERA_ID = "EFS-DEMO-001"
TYPES = ["car", "suv", "truck", "van", "pickup", "motorcycle"]
COLORS = ["black", "white", "silver", "gray", "red", "blue", "green"]
MAKES = ["Ford", "Toyota", "Chevrolet", "Honda", "Tesla", "RAM", "Nissan", "GMC"]
MODELS = {
    "Ford": ["F-150", "Explorer", "Escape", "Transit"],
    "Toyota": ["Camry", "RAV4", "Tacoma"],
    "Chevrolet": ["Silverado", "Equinox", "Tahoe"],
    "Honda": ["Civic", "Accord", "CR-V"],
    "Tesla": ["Model 3", "Model Y", "Cybertruck"],
    "RAM": ["1500", "2500", "ProMaster"],
    "Nissan": ["Altima", "Rogue", "Titan"],
    "GMC": ["Sierra", "Yukon", "Savana"],
}
COMPANIES = ["FedEx", "UPS", "Amazon", "USPS", "DHL", "Sysco"]
DIRECTIONS = ["in", "out"]
PLATE_LETTERS = "ABCDEFGHJKLMNPRSTUVWXYZ"


def _plate() -> str:
    return (
        "".join(random.choice(PLATE_LETTERS) for _ in range(3))
        + "-"
        + "".join(random.choice("0123456789") for _ in range(4))
    )


# Hour-of-day weights (UTC): a business entrance is busy in the daytime, quiet
# overnight. Used to bias demo timestamps so the Insights hourly chart looks
# like real traffic instead of noise.
_HOUR_WEIGHTS = [
    1, 1, 1, 1, 1, 2, 4, 8, 12, 14, 13, 15,   # 00..11
    16, 14, 13, 12, 14, 15, 11, 7, 4, 3, 2, 1,  # 12..23
]
_SPREAD_DAYS = 14


def _biased_time(now):
    """A timestamp within the last _SPREAD_DAYS, biased toward business hours."""
    day = random.randint(0, _SPREAD_DAYS - 1)
    hour = random.choices(range(24), weights=_HOUR_WEIGHTS, k=1)[0]
    minute = random.randint(0, 59)
    return (now - timedelta(days=day)).replace(
        hour=hour, minute=minute, second=0, microsecond=0
    )


def main(n: int = 120) -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        cam = db.get(Camera, CAMERA_ID)
        if cam is None:
            db.add(Camera(id=CAMERA_ID, name="Front Gate", location="Main entrance",
                          status="online", last_seen=_utcnow(), api_token=None))
        else:
            # The laptop demo camera uses open ingest (no pairing token), so the
            # bundled run-camera.cmd works out of the box. Clear any token a
            # prior console "register" may have set, so uploads aren't rejected.
            cam.api_token = None

        # A demo watchlist plate, then guarantee one matching vehicle below.
        watch_plate = "BAD-1234"
        if not db.query(WatchlistEntry).filter(
            WatchlistEntry.plate_normalized == normalize_plate(watch_plate)
        ).first():
            db.add(WatchlistEntry(plate_text=watch_plate, plate_normalized=normalize_plate(watch_plate),
                                  label="Banned customer", reason="Repeated trespass", active=True))
        db.commit()

        now = _utcnow()
        # "Regulars" — vehicles that keep coming back (so the Insights page has
        # real returning-visitor data). A couple are commercial fleets on a route.
        regulars = [
            {"plate": "RGL-1001", "company": "FedEx", "type": "van"},
            {"plate": "RGL-2002", "company": "Amazon", "type": "van"},
            {"plate": "RGL-3003", "company": "Sysco", "type": "truck"},
            {"plate": "RGL-4004", "company": None, "type": "pickup"},
            {"plate": "RGL-5005", "company": None, "type": "car"},
            {"plate": "RGL-6006", "company": "UPS", "type": "truck"},
        ]
        for i in range(n):
            if i == 3:
                plate, company, vtype = watch_plate, None, random.choice(TYPES)
            elif random.random() < 0.45:                 # ~45% are returning regulars
                r = random.choice(regulars)
                plate, company, vtype = r["plate"], r["company"], r["type"]
            else:                                        # one-off visitors
                plate = _plate()
                commercial = random.random() < 0.25
                company = random.choice(COMPANIES) if commercial else None
                vtype = random.choice(TYPES)
            make = random.choice(MAKES)
            db.add(VehicleEvent(
                id=str(uuid.uuid4()),
                camera_id=CAMERA_ID,
                captured_at=_biased_time(now),
                direction=random.choice(DIRECTIONS),
                plate_text=plate.upper(),
                plate_normalized=normalize_plate(plate),
                plate_confidence=round(random.uniform(0.75, 0.99), 2),
                plate_region="CA",
                vehicle_type=vtype,
                vehicle_make=make,
                vehicle_model=random.choice(MODELS[make]),
                vehicle_color=random.choice(COLORS),
                occupant_count=random.randint(1, 4),
                is_commercial=bool(company),
                company_name=company,
                confidence=round(random.uniform(0.6, 0.98), 2),
                flagged=(plate == watch_plate),
                flag_reason="Banned customer" if plate == watch_plate else None,
            ))
        db.commit()
        print(f"Seeded camera {CAMERA_ID} with {n} vehicle events "
              f"(returning regulars + 1 flagged), spread over {_SPREAD_DAYS} days.")
    finally:
        db.close()


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 120)
