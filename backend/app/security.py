"""Auth: business-owner JWT login + edge-camera ingest auth.

Password hashing uses stdlib PBKDF2 (no bcrypt/passlib dependency to build).
The owner's console endpoints require a JWT bearer token; camera ingest requires
the camera's pairing token (or a shared ingest token in dev) plus an
X-Camera-Id header.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
from base64 import urlsafe_b64decode, urlsafe_b64encode
from datetime import datetime, timedelta, timezone
from typing import Optional

# Only alphanumeric, dash, underscore — blocks path traversal and shell chars.
_CAMERA_ID_RE = re.compile(r'^[A-Za-z0-9_\-]{1,64}$')

import jwt
from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .config import get_settings
from .database import SessionLocal, get_db
from .models import Camera, User

settings = get_settings()
_PBKDF2_ROUNDS = 240_000
bearer_scheme = HTTPBearer(auto_error=False)


# --------------------------------------------------------------------------- #
# Password hashing (PBKDF2-HMAC-SHA256)
# --------------------------------------------------------------------------- #
def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ROUNDS)
    return (
        f"pbkdf2_sha256${_PBKDF2_ROUNDS}$"
        f"{urlsafe_b64encode(salt).decode()}${urlsafe_b64encode(dk).decode()}"
    )


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, rounds, salt_b64, hash_b64 = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        salt = urlsafe_b64decode(salt_b64)
        expected = urlsafe_b64decode(hash_b64)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, int(rounds))
        return hmac.compare_digest(dk, expected)
    except Exception:
        return False


# --------------------------------------------------------------------------- #
# JWT
# --------------------------------------------------------------------------- #
def create_access_token(subject: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": subject,
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def _decode_token(token: str) -> dict:
    # require exp/sub so a hand-crafted token without an expiry is never valid.
    return jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=[settings.jwt_algorithm],
        options={"require": ["exp", "sub"]},
    )


# --------------------------------------------------------------------------- #
# Dependencies
# --------------------------------------------------------------------------- #
def get_current_user(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Require a valid owner JWT; return the User."""
    unauth = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if creds is None:
        raise unauth
    try:
        payload = _decode_token(creds.credentials)
        email = payload.get("sub")
    except jwt.PyJWTError:
        raise unauth
    user = db.query(User).filter(User.email == email).first()
    if user is None:
        raise unauth
    return user


def require_owner(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> str:
    """Validate the owner JWT WITHOUT holding a request-scoped DB session open.

    ``get_current_user`` depends on ``get_db``, whose session is only released
    when the response finishes — fine for normal endpoints, but a long-lived
    streaming response (the MJPEG live view) would then pin one pooled DB
    connection for the entire duration of the stream, starving the pool. This
    dependency opens a short-lived session just to confirm the owner exists,
    closes it immediately, and returns the email. Use it for streaming routes.
    """
    unauth = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if creds is None:
        raise unauth
    try:
        payload = _decode_token(creds.credentials)
        email = payload.get("sub")
    except jwt.PyJWTError:
        raise unauth
    db = SessionLocal()
    try:
        exists = db.query(User.id).filter(User.email == email).first() is not None
    finally:
        db.close()
    if not exists:
        raise unauth
    return email


def require_camera_auth(
    x_camera_id: Optional[str] = Header(default=None, alias="X-Camera-Id"),
    creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> str:
    """Authenticate an edge camera for ingest. Returns the camera id.

    Auth precedence:
      1. If the camera is registered with a per-device ``api_token`` (the owner
         registered it by serial number), that token MUST match. Production path.
      2. Otherwise fall back to the optional global ``INGEST_TOKEN`` (or open
         ingest in local dev when neither is set), which also lets a brand-new
         unit auto-register on its first report.

    The X-Camera-Id header (the serial number) is always required.
    """
    if not x_camera_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing X-Camera-Id header",
        )
    if not _CAMERA_ID_RE.match(x_camera_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid X-Camera-Id format",
        )
    provided = creds.credentials if creds else None

    camera = db.get(Camera, x_camera_id)
    if camera is not None and camera.api_token:
        # api_token in DB is SHA-256(raw_token). Use constant-time compare.
        provided_hash = (
            hashlib.sha256(provided.encode()).hexdigest()
            if provided else ""
        )
        if not hmac.compare_digest(provided_hash, camera.api_token):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid pairing token for this camera",
            )
        return x_camera_id

    if settings.ingest_token:
        ok = provided is not None and hmac.compare_digest(provided, settings.ingest_token)
        if not ok:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or missing ingest token",
            )
    elif settings.is_production:
        # Never allow open (unauthenticated) ingest in production. Without this,
        # anyone who can reach the API could push fake events or fake "live"
        # frames for a serial number that has no pairing token yet.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Camera ingest requires a pairing token in production",
        )
    return x_camera_id
