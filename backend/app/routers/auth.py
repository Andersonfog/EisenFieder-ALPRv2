"""Business-owner authentication — the only human login in the whole system."""

from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict, deque

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import get_db
from ..models import User
from ..schemas import LoginIn, TokenOut, UserOut
from ..security import create_access_token, get_current_user, verify_password

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
logger = logging.getLogger("eisenfieder.auth")

# Simple in-memory login rate limiter to blunt brute-force guessing. Keyed by
# BOTH client IP and target email, so an attacker rotating IPs still can't
# hammer the owner's account, and one IP can't spray many emails either.
# For a multi-server deployment, back this with Redis instead.
_attempts: dict[str, deque] = defaultdict(deque)
_attempts_lock = threading.Lock()


def _rate_limited(ip: str, email: str) -> bool:
    settings = get_settings()
    now = time.monotonic()
    window = settings.login_window_seconds
    limited = False
    with _attempts_lock:
        for key in (f"ip:{ip}", f"email:{email.strip().lower()}"):
            dq = _attempts[key]
            while dq and now - dq[0] > window:
                dq.popleft()
            if len(dq) >= settings.login_max_attempts:
                limited = True
            else:
                dq.append(now)
    return limited


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)) -> TokenOut:
    ip = request.client.host if request.client else "unknown"
    if _rate_limited(ip, body.email):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts. Please wait a few minutes and try again.",
        )
    user = db.query(User).filter(User.email == body.email).first()
    # Always run the full PBKDF2 hash even for unknown emails — prevents timing
    # side-channel that would let an attacker enumerate valid email addresses.
    _DUMMY_HASH = (
        "pbkdf2_sha256$240000$AAAAAAAAAAAAAAAA$"
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=="
    )
    stored = user.password_hash if user is not None else _DUMMY_HASH
    password_ok = verify_password(body.password, stored)
    if user is None or not password_ok:
        logger.warning("AUTH FAIL ip=%s email=%s", ip, body.email)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials"
        )
    logger.info("AUTH OK ip=%s email=%s", ip, user.email)
    return TokenOut(access_token=create_access_token(user.email))


@router.get("/me", response_model=UserOut)
def me(current: User = Depends(get_current_user)) -> User:
    return current
