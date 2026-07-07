# EisenFieder Surveillance — backend

FastAPI + SQLAlchemy. Single-tenant (one business owner). Runs on SQLite + local
file storage with zero external services.

## Quick start

```powershell
pip install -r requirements.txt
python -m scripts.seed_demo          # optional demo data
uvicorn app.main:app --reload
python tests/test_api.py             # self-running tests (7 pass)
```

## API (all under `/api/v1`)

| Method & path | Auth | Purpose |
|---|---|---|
| `GET /health` | none | liveness check |
| `POST /auth/login` | none | owner login → JWT (rate-limited) |
| `GET /auth/me` | owner | current owner |
| `POST /cameras` | owner | register a camera by serial → pairing token (shown once) |
| `GET /cameras` · `GET /cameras/{id}` | owner | list / view cameras |
| `PUT /cameras/{id}/settings` | owner | excluded types, capture toggles, threshold |
| `POST /cameras/{id}/regenerate-token` · `DELETE /cameras/{id}` | owner | manage pairing |
| `GET /cameras/{id}/config` | camera | edge pulls its own settings |
| `POST /vehicles` | camera | ingest one vehicle event (+image, +plate crop); idempotent |
| `GET /vehicles` | owner | **search** by plate, type, color, make, company, direction, commercial, flagged, time |
| `GET /vehicles/{id}` | owner | one event |
| `GET /vehicles.csv` | owner | export the filtered log |
| `GET /stats` | owner | totals + breakdown by type/direction |
| `GET /watchlist` · `POST /watchlist` · `PATCH /watchlist/{id}` · `DELETE /watchlist/{id}` | owner | manage flagged plates |
| `GET /media/{key}` | owner | **owner-only** streamed stills |

### Ingest contract (what a camera sends)

`POST /api/v1/vehicles` as `multipart/form-data`:
- header `X-Camera-Id: <serial>` and `Authorization: Bearer <pairing-token>`
- `metadata` — JSON matching `schemas.VehicleEventMetadata`
  (`event_uuid`, `camera_id`, `captured_at`, `direction`, `plate_text`,
  `plate_confidence`, `plate_region`, `vehicle_type`, `vehicle_make`,
  `vehicle_color`, `occupant_count`, `is_commercial`, `company_name`,
  `confidence`)
- `image` — the scene still (optional)
- `plate_image` — cropped plate (optional)

`event_uuid` makes ingest idempotent: a re-sent event over a flaky link is a
success (`409 duplicate`), never a duplicate row. A plate matching an active
watchlist entry is stored `flagged=true` with the reason.

## Configuration

All via environment / `.env` (see `.env.example`). Key ones: `OWNER_EMAIL`,
`OWNER_PASSWORD`, `JWT_SECRET`, `CORS_ORIGINS`, `MEDIA_DIR`, `INGEST_TOKEN`,
`DATA_RETENTION_DAYS`, `APP_ENV` (`production` refuses to boot on weak secrets).

## Files

```
app/
  config.py      env-driven settings + production security checks
  database.py    SQLAlchemy engine/session + additive column migrations
  models.py      User (owner), Camera, VehicleEvent, WatchlistEntry
  schemas.py     pydantic request/response models
  security.py    PBKDF2 hashing, JWT, owner + camera auth dependencies
  storage.py     local still storage (keys only; served via auth'd /media)
  plates.py      plate normalization for matching/search
  seed.py        creates the single owner on first boot
  routers/       auth, cameras, vehicles, watchlist, media
scripts/
  seed_demo.py   demo camera + 60 sample vehicles
  purge_old.py   delete records/images past the retention window
tests/
  test_api.py    self-running API tests
```
