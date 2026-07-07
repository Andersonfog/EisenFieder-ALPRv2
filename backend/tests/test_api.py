"""Backend API tests using FastAPI's TestClient (SQLite + local storage).

    cd backend
    python tests/test_api.py     # self-runner
    pytest tests/                # if pytest is installed

Environment is configured BEFORE importing the app so it points at a throwaway
SQLite DB and a temp media directory.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import uuid
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

# --- Configure a throwaway environment before app import ---
_TMP = tempfile.mkdtemp(prefix="efs_api_")
os.environ["DATABASE_URL"] = f"sqlite:///{Path(_TMP) / 'test.db'}"
os.environ["MEDIA_DIR"] = str(Path(_TMP) / "media")
os.environ["JWT_SECRET"] = "test-secret"
os.environ["OWNER_EMAIL"] = "owner@eisenfieder.local"
os.environ["OWNER_PASSWORD"] = "changeme123"
os.environ["INGEST_TOKEN"] = ""  # open ingest for the test
os.environ["CORS_ORIGINS"] = "http://localhost:5173"
os.environ["LOGIN_MAX_ATTEMPTS"] = "1000"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

client = TestClient(app)
CAMERA = "EFS-TEST-001"
CAMERA_TOKEN: str | None = None   # set once the camera is registered
FAKE_JPEG = b"\xff\xd8\xff\xe0fakejpegbytes"


def _token() -> str:
    r = client.post("/api/v1/auth/login", json={
        "email": "owner@eisenfieder.local", "password": "changeme123",
    })
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _auth() -> dict:
    return {"Authorization": f"Bearer {_token()}"}


def _ingest(token=None, profile_image=False, **over):
    # A registered camera must present its pairing token. Pass token="" to
    # deliberately send an unauthenticated request.
    tok = token if token is not None else CAMERA_TOKEN
    headers = {"X-Camera-Id": CAMERA}
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    meta = {
        "event_uuid": over.pop("event_uuid", str(uuid.uuid4())),
        "camera_id": CAMERA,
        "captured_at": "2026-06-24T10:00:00+00:00",
        "direction": "in",
        "plate_text": "ABC-1234",
        "plate_confidence": 0.93,
        "plate_region": "CA",
        "vehicle_type": "truck",
        "vehicle_make": "Ford",
        "vehicle_color": "white",
        "occupant_count": 2,
        "is_commercial": True,
        "company_name": "FedEx",
        "confidence": 0.9,
    }
    meta.update(over)
    files = {
        "image": ("shot.jpg", FAKE_JPEG, "image/jpeg"),
        "plate_image": ("plate.jpg", FAKE_JPEG, "image/jpeg"),
    }
    if profile_image:
        files["profile_image"] = ("side.jpg", FAKE_JPEG, "image/jpeg")
    return client.post(
        "/api/v1/vehicles",
        data={"metadata": json.dumps(meta)},
        files=files,
        headers=headers,
    )


def test_health():
    r = client.get("/api/v1/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_login_required_everywhere():
    # No token -> blocked on the console endpoints.
    assert client.get("/api/v1/vehicles").status_code == 401
    assert client.get("/api/v1/cameras").status_code == 401
    assert client.get("/api/v1/stats").status_code == 401
    assert client.post("/api/v1/auth/login", json={
        "email": "owner@eisenfieder.local", "password": "wrong",
    }).status_code == 401


def test_register_camera_and_ingest():
    global CAMERA_TOKEN
    r = client.post("/api/v1/cameras",
                    json={"serial_number": CAMERA, "name": "Front Gate", "location": "Entrance"},
                    headers=_auth())
    assert r.status_code == 201, r.text
    CAMERA_TOKEN = r.json()["api_token"]
    assert CAMERA_TOKEN
    assert "BACKEND_API_TOKEN" in r.json()["env_snippet"]

    # A registered camera cannot ingest without its pairing token (security).
    assert _ingest(token="", event_uuid="evt-noauth").status_code == 401

    r = _ingest(event_uuid="evt-1")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "created"
    # Re-send from the SAME camera -> update-in-place, never a new row.
    r = _ingest(event_uuid="evt-1")
    assert r.status_code == 200 and r.json()["status"] == "updated"
    # A DIFFERENT camera reusing the uuid is rejected as a duplicate.
    r2 = client.post("/api/v1/cameras",
                     json={"serial_number": "EFS-OTHER-01", "name": "Other"},
                     headers=_auth())
    assert r2.status_code == 201
    other_tok = r2.json()["api_token"]
    resp = client.post(
        "/api/v1/vehicles",
        data={"metadata": json.dumps({"event_uuid": "evt-1",
                                      "camera_id": "EFS-OTHER-01"})},
        headers={"X-Camera-Id": "EFS-OTHER-01",
                 "Authorization": f"Bearer {other_tok}"},
    )
    assert resp.status_code == 409


def test_live_preview_auto_registers_dev_camera():
    """A local USB camera should appear in the console as soon as live preview starts."""
    camera_id = "EFS-USB-AUTO"
    body = f"EFSF {len(FAKE_JPEG)} 20.0 5.5 profile=workstation_track\n".encode() + FAKE_JPEG
    r = client.post(
        f"/api/v1/cameras/{camera_id}/live/stream",
        content=body,
        headers={"X-Camera-Id": camera_id},
    )
    assert r.status_code == 204, r.text

    r = client.get("/api/v1/cameras", headers=_auth())
    assert r.status_code == 200, r.text
    cameras = {c["id"]: c for c in r.json()}
    assert camera_id in cameras
    assert cameras[camera_id]["status"] == "online"

    r = client.get(f"/api/v1/cameras/{camera_id}/live/status", headers=_auth())
    assert r.status_code == 200, r.text
    status = r.json()
    assert status["online"] is True
    assert status["profile"] == "workstation_track"


def test_live_event_updates_in_place():
    """The edge logs a provisional row the instant a vehicle is confirmed
    (pending=true, maybe no plate yet), then enriches the SAME row when the
    pass ends - one event in the log, not two."""
    r = _ingest(event_uuid="evt-live-1", plate_text=None, direction="unknown",
                pending=True)
    assert r.status_code == 201, r.text

    r = client.get("/api/v1/vehicles/evt-live-1", headers=_auth())
    body = r.json()
    assert body["pending"] is True and body["plate_text"] is None
    assert body["image_url"].endswith("?v=p")   # provisional image version
    first_seen = body["captured_at"]

    # The pass ends: same uuid, now with the fused plate and a direction.
    r = _ingest(event_uuid="evt-live-1", plate_text="LIV-3344", direction="in",
                pending=False, captured_at="2026-06-24T10:00:30+00:00")
    assert r.status_code == 200 and r.json()["status"] == "updated"

    r = client.get("/api/v1/vehicles/evt-live-1", headers=_auth())
    body = r.json()
    assert body["pending"] is False
    assert body["plate_text"] == "LIV-3344" and body["direction"] == "in"
    assert body["image_url"].endswith("?v=f")   # cache-busted on finalize
    # The row keeps its first-seen time (its spot in the log).
    assert body["captured_at"] == first_seen

    # Searching by the final plate finds the single, updated row.
    r = client.get("/api/v1/vehicles", params={"plate": "liv3344"}, headers=_auth())
    items = r.json()["items"]
    assert len(items) == 1 and items[0]["id"] == "evt-live-1"


def test_search_filters():
    # Seed a couple of distinct vehicles.
    _ingest(event_uuid="evt-car", plate_text="ZZZ-9999", vehicle_type="car",
            is_commercial=False, company_name=None, direction="out")
    _ingest(event_uuid="evt-van", plate_text="VAN-0001", vehicle_type="van",
            is_commercial=True, company_name="Amazon", direction="in")

    # Partial plate search (normalized so "abc1234" finds "ABC-1234").
    r = client.get("/api/v1/vehicles", params={"plate": "abc1234"}, headers=_auth())
    assert r.status_code == 200, r.text
    assert any(i["plate_text"] == "ABC-1234" for i in r.json()["items"])

    # Filter by vehicle type.
    r = client.get("/api/v1/vehicles", params={"vehicle_type": "van"}, headers=_auth())
    assert all(i["vehicle_type"] == "van" for i in r.json()["items"])

    # Filter by company (partial, case-insensitive).
    r = client.get("/api/v1/vehicles", params={"company": "amaz"}, headers=_auth())
    assert any(i["company_name"] == "Amazon" for i in r.json()["items"])

    # Filter by direction.
    r = client.get("/api/v1/vehicles", params={"direction": "out"}, headers=_auth())
    assert all(i["direction"] == "out" for i in r.json()["items"])


def test_media_is_owner_only():
    _ingest(event_uuid="evt-media")
    r = client.get("/api/v1/vehicles/evt-media", headers=_auth())
    assert r.status_code == 200, r.text
    image_url = r.json()["image_url"]
    assert image_url and image_url.startswith("/api/v1/media/")

    # Without the owner token, footage must NOT be readable.
    assert client.get(image_url).status_code == 401
    # With the token it streams.
    r = client.get(image_url, headers=_auth())
    assert r.status_code == 200 and r.content == FAKE_JPEG

    # Path-traversal is refused.
    assert client.get("/api/v1/media/../../secret", headers=_auth()).status_code in (400, 404)


def test_watchlist_flagging():
    r = client.post("/api/v1/watchlist",
                    json={"plate_text": "flag 777", "label": "Stolen", "reason": "BOLO"},
                    headers=_auth())
    assert r.status_code == 201, r.text

    # A vehicle with that plate (any formatting) is flagged on ingest.
    r = _ingest(event_uuid="evt-flag", plate_text="FLAG-777")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["flagged"] is True and body["flag_reason"] == "Stolen"

    # Searchable by flagged=true.
    r = client.get("/api/v1/vehicles", params={"flagged": "true"}, headers=_auth())
    assert any(i["id"] == "evt-flag" for i in r.json()["items"])


def test_side_profile_stored_and_matched():
    """The side-profile still is stored + served owner-only, and events whose
    appearance fingerprints look alike are matched by /similar."""
    # Two look-alike fingerprints and one clearly different vehicle.
    vec_a = [0.9, 0.1, 0.0, 0.3]
    vec_b = [0.85, 0.15, 0.05, 0.28]     # cosine vs vec_a ~0.99
    vec_c = [0.0, 1.0, 0.0, 0.0]         # cosine vs vec_a ~0.11
    r = _ingest(event_uuid="prof-1", plate_text="SIM-0001", profile_image=True,
                metadata={"profile_vec": vec_a, "profile_v": 1})
    assert r.status_code == 201, r.text
    _ingest(event_uuid="prof-2", plate_text="SIM-0002", profile_image=True,
            metadata={"profile_vec": vec_b, "profile_v": 1})
    _ingest(event_uuid="prof-3", plate_text="DIF-0003", profile_image=True,
            metadata={"profile_vec": vec_c, "profile_v": 1})
    # Same-looking vectors but a different fingerprint VERSION never match.
    _ingest(event_uuid="prof-4", plate_text="VER-0004",
            metadata={"profile_vec": vec_a, "profile_v": 2})

    # The profile still is exposed as an owner-only URL and streams.
    r = client.get("/api/v1/vehicles/prof-1", headers=_auth())
    url = r.json()["profile_image_url"]
    assert url and url.startswith("/api/v1/media/") and "_side" in url
    assert client.get(url).status_code == 401            # owner-only
    r = client.get(url, headers=_auth())
    assert r.status_code == 200 and r.content == FAKE_JPEG

    # Look-alike matching: prof-2 matches, prof-3/prof-4 don't.
    r = client.get("/api/v1/vehicles/prof-1/similar", headers=_auth())
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    ids = [i["event"]["id"] for i in items]
    assert "prof-2" in ids
    assert "prof-3" not in ids and "prof-4" not in ids
    top = items[0]
    assert top["score"] > 0.9
    assert top["event"]["plate_text"] == "SIM-0002"

    # An event without a fingerprint answers honestly with no matches.
    _ingest(event_uuid="prof-none")
    r = client.get("/api/v1/vehicles/prof-none/similar", headers=_auth())
    assert r.status_code == 200 and r.json()["items"] == []

    # Owner login required.
    assert client.get("/api/v1/vehicles/prof-1/similar").status_code == 401


def test_vehicle_updates_stream():
    """The push channel greets immediately with a data: line (the console
    re-fetches on every such ping) and requires the owner login.

    TestClient buffers whole responses, so the test uses ?limit=1 to ask the
    stream to close itself after the greeting instead of running forever."""
    assert client.get("/api/v1/vehicles/updates?limit=1").status_code == 401
    r = client.get("/api/v1/vehicles/updates?limit=1", headers=_auth())
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    assert r.text.startswith("data:")


def test_live_stream_ingest():
    """The edge can stream MANY frames over ONE upload (EFSF packets); each
    becomes the camera's latest preview frame, with the fps stats parsed."""
    jpeg1 = b"\xff\xd8\xff\xe0" + b"frame-one"
    jpeg2 = b"\xff\xd8\xff\xe0" + b"frame-two-bigger"
    body = (f"EFSF {len(jpeg1)} 29.5 6.1\n".encode() + jpeg1
            + f"EFSF {len(jpeg2)} 30.0 6.4\n".encode() + jpeg2)
    r = client.post(f"/api/v1/cameras/{CAMERA}/live/stream",
                    content=body,
                    headers={"X-Camera-Id": CAMERA,
                             "Authorization": f"Bearer {CAMERA_TOKEN}"})
    assert r.status_code == 204, r.text

    # The LAST streamed frame is what the owner sees.
    r = client.get(f"/api/v1/cameras/{CAMERA}/live", headers=_auth())
    assert r.status_code == 200 and r.content == jpeg2
    r = client.get(f"/api/v1/cameras/{CAMERA}/live/status", headers=_auth())
    s = r.json()
    assert s["online"] is True
    assert s["capture_fps"] == 30.0 and s["detect_fps"] == 6.4

    # Garbage framing is rejected; camera auth is required.
    r = client.post(f"/api/v1/cameras/{CAMERA}/live/stream",
                    content=b"NOPE not a packet\n",
                    headers={"X-Camera-Id": CAMERA,
                             "Authorization": f"Bearer {CAMERA_TOKEN}"})
    assert r.status_code == 400
    assert client.post(f"/api/v1/cameras/{CAMERA}/live/stream",
                       content=body,
                       headers={"X-Camera-Id": CAMERA}).status_code == 401


def test_learns_returning_vehicles():
    """The system learns visit history: same plate = same vehicle (identity);
    no plate but a near-identical side-profile fingerprint = a clearly-labeled
    appearance match; strangers get no visit tag."""
    # Two visits by plate REG-7777 (different event uuids = different passes).
    _ingest(event_uuid="reg-1", plate_text="REG-7777")
    _ingest(event_uuid="reg-2", plate_text="REG-7777")
    r = client.get("/api/v1/vehicles/reg-2", headers=_auth())
    visit = r.json()["visit"]
    assert visit and visit["count"] == 2 and visit["by"] == "plate"
    # The first visit has no history to learn from.
    assert client.get("/api/v1/vehicles/reg-1", headers=_auth()).json()["visit"] is None

    # No plate readable, but the car LOOKS like one seen before -> appearance.
    # (Vectors chosen far from every other test event's fingerprint: real
    # fingerprints have ~110 dimensions; these tiny stand-ins collide easily.)
    _ingest(event_uuid="anon-1", plate_text=None,
            metadata={"profile_vec": [0.05, 0.02, 0.95, 0.30], "profile_v": 1})
    _ingest(event_uuid="anon-2", plate_text=None,
            metadata={"profile_vec": [0.06, 0.03, 0.94, 0.31], "profile_v": 1})
    r = client.get("/api/v1/vehicles/anon-2", headers=_auth())
    visit = r.json()["visit"]
    assert visit and visit["count"] == 2 and visit["by"] == "appearance", visit

    # A different-looking plateless car is honestly untagged.
    _ingest(event_uuid="anon-3", plate_text=None,
            metadata={"profile_vec": [0.5, 0.5, 0.5, 0.5], "profile_v": 1})
    assert client.get("/api/v1/vehicles/anon-3", headers=_auth()).json()["visit"] is None


def test_stats_and_csv():
    r = client.get("/api/v1/stats", headers=_auth())
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["total_vehicles"] >= 1 and s["total_cameras"] >= 1
    assert isinstance(s["by_type"], list)

    r = client.get("/api/v1/vehicles.csv", headers=_auth())
    assert r.status_code == 200
    assert r.text.splitlines()[0].startswith("event_uuid,camera_id")


def test_event_uuid_path_traversal_rejected():
    # SECURITY REGRESSION: event_uuid is concatenated into the on-disk still key
    # (f"{camera_id}/{event_uuid}.jpg"). A traversal payload must be refused at
    # the schema boundary (422), and a normal uuid must still ingest.
    assert _ingest(event_uuid="../../../../etc/pwned").status_code == 422
    assert _ingest(event_uuid="a/b").status_code == 422
    assert _ingest(event_uuid=str(uuid.uuid4())).status_code == 201

    # Storage-layer backstop: an unsafe key raises instead of escaping MEDIA_DIR.
    from app.storage import storage_singleton
    raised = False
    try:
        storage_singleton().save("../../escape.jpg", b"\xff\xd8x")
    except ValueError:
        raised = True
    assert raised, "storage.save must refuse path-traversal keys"


def test_csv_formula_injection_neutralized():
    # SECURITY REGRESSION: ingest-supplied text (company_name, etc.) is exported
    # to CSV. A leading =/+/-/@ would execute as a formula in Excel/Sheets, so it
    # must be neutralized with a leading apostrophe.
    payload = '=HYPERLINK("http://evil","x")'
    assert _ingest(event_uuid="evt-csvinj", company_name=payload,
                   is_commercial=True).status_code == 201
    r = client.get("/api/v1/vehicles.csv", headers=_auth())
    assert r.status_code == 200
    line = next(ln for ln in r.text.splitlines() if "HYPERLINK" in ln)
    assert "'=HYPERLINK" in line, "formula cell was not neutralized"

    import csv as _csv
    import io as _io
    row = next(_csv.reader(_io.StringIO(line)))
    assert not any(c.startswith("=") for c in row), "a raw formula cell survived"


def test_analytics_insights():
    # Two sightings of the same plate -> a returning vehicle; a commercial one.
    _ingest(event_uuid="evt-rep-1", plate_text="RPT-100", is_commercial=False, company_name=None)
    _ingest(event_uuid="evt-rep-2", plate_text="RPT-100", is_commercial=False, company_name=None)
    _ingest(event_uuid="evt-comp", plate_text="CMP-9", is_commercial=True, company_name="Acme Freight")

    # Owner-only.
    assert client.get("/api/v1/analytics").status_code == 401

    r = client.get("/api/v1/analytics", params={"days": 365}, headers=_auth())
    assert r.status_code == 200, r.text
    a = r.json()
    assert a["total_events"] >= 3
    # Buckets default to UTC until the owner changes the timezone setting.
    assert a["timezone"] == "UTC"
    assert len(a["by_hour"]) == 24 and len(a["by_weekday"]) == 7
    assert a["unique_plates"] >= 1
    # The repeated plate shows up as a returning vehicle with 2+ visits.
    reps = {v["plate"]: v["visits"] for v in a["repeat_visitors"]}
    assert any(k.startswith("RPT") and n >= 2 for k, n in reps.items()), reps
    # The commercial company is counted.
    assert any(c["name"] == "Acme Freight" for c in a["top_companies"])
    assert 0.0 <= a["commercial_ratio"] <= 1.0

    # Range is validated.
    assert client.get("/api/v1/analytics", params={"days": 0}, headers=_auth()).status_code == 422


def test_settings_timezone_shifts_buckets():
    # Owner-only.
    assert client.get("/api/v1/settings").status_code == 401

    # Default timezone is UTC and a friendly picker list is offered.
    r = client.get("/api/v1/settings", headers=_auth())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["timezone"] == "UTC"
    assert "America/New_York" in body["common_timezones"]

    # A bogus timezone is rejected.
    assert client.put("/api/v1/settings", json={"timezone": "Mars/Olympus"},
                      headers=_auth()).status_code == 422

    # Set a real timezone; it persists and analytics re-buckets into local time.
    r = client.put("/api/v1/settings", json={"timezone": "America/New_York"},
                   headers=_auth())
    assert r.status_code == 200 and r.json()["timezone"] == "America/New_York"

    # Every test event was ingested at 10:00 UTC, which is 06:00 in New York
    # (EDT, UTC-4 in June). So the whole hour histogram must shift 10 -> 6.
    r = client.get("/api/v1/analytics", params={"days": 365}, headers=_auth())
    a = r.json()
    assert a["timezone"] == "America/New_York"
    assert a["by_hour"][6]["count"] == a["total_events"], a["by_hour"]
    assert a["by_hour"][10]["count"] == 0
    assert a["busiest_hour"] == 6

    # Restore UTC so downstream ordering isn't surprising.
    client.put("/api/v1/settings", json={"timezone": "UTC"}, headers=_auth())


def test_live_stream_is_owner_only():
    # SECURITY REGRESSION: the MJPEG stream must require an owner JWT. Auth is a
    # dependency, so rejection happens before any streaming begins (these return
    # immediately). We deliberately do NOT exercise the authorized 200 path here:
    # its body is an infinite stream that would deadlock the synchronous
    # TestClient transport. The owner-accepted path is covered live in the
    # browser verification instead.
    url = f"/api/v1/cameras/{CAMERA}/live/stream"
    assert client.get(url).status_code == 401
    # A camera pairing token is not an owner JWT.
    assert client.get(
        url, headers={"Authorization": f"Bearer {CAMERA_TOKEN}"}
    ).status_code == 401


def _run_all():
    # Definition order (not alphabetical): registration must precede ingests.
    tests = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    passed = 0
    for t in tests:
        t()
        print(f"  PASS  {t.__name__}")
        passed += 1
    print(f"\n{passed}/{len(tests)} backend tests passed.")


if __name__ == "__main__":
    _run_all()
