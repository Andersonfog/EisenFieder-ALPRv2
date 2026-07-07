"""Create the single business-owner account on first boot."""

from __future__ import annotations

import logging

from .config import get_settings
from .database import SessionLocal
from .models import User
from .security import hash_password

logger = logging.getLogger(__name__)


def seed_owner() -> None:
    settings = get_settings()
    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.email == settings.owner_email).first()
        if existing is not None:
            return
        db.add(
            User(
                email=settings.owner_email,
                password_hash=hash_password(settings.owner_password),
            )
        )
        db.commit()
        logger.info("Created owner account: %s", settings.owner_email)
    finally:
        db.close()
