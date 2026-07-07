"""FastAPI application entrypoint for EisenFieder Surveillance.

Run locally (SQLite + local file storage, no external services):
    cd backend
    pip install -r requirements.txt
    uvicorn app.main:app --reload

Security note: captured images are NOT served from a public folder. They are
streamed only by the authenticated /api/v1/media endpoint, so footage can't be
read without the business owner's login.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from . import models  # noqa: F401  (ensure models are imported before create_all)
from .config import get_settings
from .database import Base, engine, migrate_columns
from .routers import (
    analytics, auth, cameras, live, media, settings as settings_router,
    vehicles, watchlist,
)
from .seed import seed_owner

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("eisenfieder.surveillance")


def create_app() -> FastAPI:
    settings = get_settings()

    # Fail fast on insecure config in production; warn loudly in development.
    problems = settings.security_warnings()
    if problems:
        if settings.is_production:
            raise RuntimeError(
                "Refusing to start in production with insecure config:\n - "
                + "\n - ".join(problems)
            )
        for p in problems:
            logger.warning("SECURITY (dev only - fix before production): %s", p)

    Base.metadata.create_all(bind=engine)
    migrate_columns()
    seed_owner()

    app = FastAPI(
        title="EisenFieder Surveillance API",
        version="0.1.0",
        description="Owner-only entrance-camera surveillance: vehicle, plate and "
        "occupant logging with searchable history.",
    )

    # Standard browser security headers on every response.
    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Permitted-Cross-Domain-Policies"] = "none"
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=()"
        )
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        # Blocks other websites from embedding responses via <img>/<script> tags
        # (the console fetches everything through CORS, which stays allowed).
        response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
        # Surveillance data must never land in a shared/proxy cache. Endpoints
        # that want caching (e.g. immutable stills) set their own header, which
        # wins because we only fill in a default here.
        if "cache-control" not in response.headers:
            response.headers["Cache-Control"] = "no-store"
        # The console fetches media as blob: URLs so blob: must be in img-src.
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; "
            "script-src 'self'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' blob: data:; "
            "connect-src 'self'; "
            "font-src 'self'; "
            "frame-ancestors 'none'"
        )
        if settings.is_production:
            response.headers["Strict-Transport-Security"] = (
                "max-age=63072000; includeSubDomains"
            )
        return response

    # The console authenticates with a bearer token (no cookies), so we allow the
    # configured origins without credentialed CORS.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_origin_regex=settings.cors_origin_regex,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(auth.router)
    app.include_router(cameras.router)
    app.include_router(live.router)
    app.include_router(vehicles.router)
    app.include_router(watchlist.router)
    app.include_router(media.router)
    app.include_router(analytics.router)
    app.include_router(settings_router.router)

    @app.get("/api/v1/health", tags=["meta"])
    def health() -> dict:
        return {"status": "ok", "service": "eisenfieder-surveillance"}

    logger.info("EisenFieder Surveillance backend ready (business=%s)", settings.business_name)
    return app


app = create_app()
