"""Backend settings for EisenFieder Surveillance, read from environment variables.

No pydantic-settings dependency — a plain class keeps the install lean. Defaults
make the service run locally with zero external services (SQLite + local files).

This product is single-tenant: ONE business, ONE owner login. Everything the
camera captures belongs to that owner and nobody else can read it.
"""

from __future__ import annotations

import os
from functools import lru_cache


def _load_dotenv() -> None:
    """Best-effort .env loader (python-dotenv is optional)."""
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except Exception:
        pass


# Known-insecure default values that must never be used in production.
_DEFAULT_JWT_SECRET = "dev-insecure-secret-change-me"
_DEFAULT_OWNER_PASSWORD = "changeme123"


class Settings:
    def __init__(self) -> None:
        _load_dotenv()
        # Deployment mode: "development" (default) or "production".
        self.app_env = os.getenv("APP_ENV", "development").strip().lower()
        self.is_production = self.app_env in ("production", "prod")

        # Branding shown in the console.
        self.business_name = os.getenv("BUSINESS_NAME", "Your Business")

        # Default display timezone for Insights (an IANA name like
        # "America/New_York"). This is only the fallback: the owner can change it
        # in the console, which persists to the database and wins over this.
        self.business_timezone = os.getenv("BUSINESS_TIMEZONE", "UTC").strip() or "UTC"

        # Database
        self.database_url = os.getenv("DATABASE_URL", "sqlite:///./surveillance.db")

        # Owner JWT auth — the only human login in the whole system.
        self.jwt_secret = os.getenv("JWT_SECRET", _DEFAULT_JWT_SECRET)
        self.jwt_algorithm = "HS256"
        self.jwt_expire_minutes = int(os.getenv("JWT_EXPIRE_MINUTES", "60"))
        self.owner_email = os.getenv("OWNER_EMAIL", "owner@eisenfieder.local")
        self.owner_password = os.getenv("OWNER_PASSWORD", _DEFAULT_OWNER_PASSWORD)

        # Camera ingest auth ("" = open ingest, for local dev only).
        self.ingest_token = os.getenv("INGEST_TOKEN", "").strip()

        # Abuse limits
        self.max_upload_mb = int(os.getenv("MAX_UPLOAD_MB", "10"))
        self.login_max_attempts = int(os.getenv("LOGIN_MAX_ATTEMPTS", "10"))
        self.login_window_seconds = int(os.getenv("LOGIN_WINDOW_SECONDS", "300"))

        # Media storage. Captured stills live on disk under MEDIA_DIR and are
        # served ONLY through the authenticated /api/v1/media endpoint — there is
        # no public folder, so footage can't be read without the owner's login.
        self.media_dir = os.getenv("MEDIA_DIR", "./media")

        # A camera is considered offline if it hasn't reported in this long.
        self.camera_offline_after_seconds = int(
            os.getenv("CAMERA_OFFLINE_AFTER_SECONDS", "600")
        )

        # Privacy / retention: if > 0, vehicle records and their images older
        # than this many days can be purged (see scripts/purge_old.py). 0 = keep.
        self.data_retention_days = int(os.getenv("DATA_RETENTION_DAYS", "0"))

        # Text alerts to the owner when a watchlisted plate is seen. Real SMS
        # needs Twilio creds + OWNER_PHONE; without them the alert is logged.
        self.alerts_enabled = os.getenv("ALERTS_ENABLED", "true").strip().lower() in (
            "1", "true", "yes", "on"
        )
        self.owner_phone = os.getenv("OWNER_PHONE", "").strip()
        self.twilio_account_sid = os.getenv("TWILIO_ACCOUNT_SID", "").strip()
        self.twilio_auth_token = os.getenv("TWILIO_AUTH_TOKEN", "").strip()
        self.twilio_from_number = os.getenv("TWILIO_FROM_NUMBER", "").strip()

        # CORS — default to the local console only (not "*"), so a fresh install
        # isn't wide open. Override CORS_ORIGINS for your real console URL.
        # The surveillance console's Vite dev server runs on 5174 (5173 is the
        # separate predator dashboard), so allow both localhost + 127.0.0.1 there.
        origins = os.getenv(
            "CORS_ORIGINS",
            "http://localhost:5174,http://127.0.0.1:5174,"
            "http://localhost:5173,http://127.0.0.1:5173",
        )
        self.cors_origins = [o.strip() for o in origins.split(",") if o.strip()] or [
            "http://localhost:5173"
        ]

        # In development, also accept any localhost / private-LAN origin on any
        # port, so it doesn't matter whether you open the console via 127.0.0.1,
        # localhost, or your machine's LAN IP (Vite prints all three). Production
        # ignores this and uses only the explicit list above.
        self.cors_origin_regex = None if self.is_production else (
            r"http://(localhost|127\.0\.0\.1|"
            r"10\.\d{1,3}\.\d{1,3}\.\d{1,3}|"
            r"192\.168\.\d{1,3}\.\d{1,3}|"
            r"172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})(:\d+)?"
        )

    def security_warnings(self) -> list[str]:
        """Return human-readable security problems with the current config.

        Used to warn in development and to refuse startup in production.
        """
        problems: list[str] = []
        if self.jwt_secret == _DEFAULT_JWT_SECRET or len(self.jwt_secret) < 32:
            problems.append(
                "JWT_SECRET is the default or too short - set a random 32+ character value."
            )
        if self.owner_password == _DEFAULT_OWNER_PASSWORD or len(self.owner_password) < 10:
            problems.append(
                "OWNER_PASSWORD is the default or too short - set a strong password."
            )
        if "*" in self.cors_origins:
            problems.append(
                "CORS_ORIGINS is '*' (any website) - set it to your console's URL only."
            )
        return problems


@lru_cache
def get_settings() -> Settings:
    return Settings()
