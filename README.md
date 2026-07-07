# EisenFieder ALPR

On-premises automatic license plate recognition for entrances, lots, yards, and private business sites. The system captures vehicle passes from a camera, tracks each vehicle through the scene, fuses multiple plate reads into one answer, and stores searchable events in a local FastAPI + SQLite backend.

The project is hardware agnostic. Run it on a Windows laptop with a USB camera for development, then move the same stack to a workstation, mini PC, Jetson, or lower-power edge box when you decide how much compute you want to spend.

## What It Runs

- `backend/` - FastAPI service, SQLite database, media storage, auth, camera registry, watchlist, analytics.
- `dashboard/` - React/Vite operations console for live view, plate log, camera settings, watchlist, and insights.
- `edge/` - camera process that captures frames, detects/tracks vehicles, reads plates, and streams live preview.

## Fast Windows USB Camera Run

From a fresh clone on the laptop:

```powershell
install-usb.cmd
start-usb-camera.cmd
```

That creates `.venv`, installs backend and edge USB dependencies, installs the
dashboard packages, opens the backend, opens the dashboard, starts the USB
camera, and opens `http://127.0.0.1:5174`.

Sign in:

```text
owner@eisenfieder.local
changeme123
```

If Windows reports the camera as index `1` or `2`, run:

```powershell
edge\check-camera.cmd
start-usb-camera.cmd 1
```

The USB launcher uses camera id `EFS-USB-001` by default. To use a different id:

```powershell
start-usb-camera.cmd 1 EFS-USB-SIDE
```

## Manual Local Run

Use three terminals from the repository root if you want to start each piece by
hand.

Terminal 1, backend:

```powershell
cd backend
..\.venv\Scripts\activate
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Terminal 2, dashboard:

```powershell
cd dashboard
npm run dev -- --host 127.0.0.1 --port 5174
```

Open `http://127.0.0.1:5174` and sign in:

```text
owner@eisenfieder.local
changeme123
```

Terminal 3, USB camera:

```powershell
cd edge
..\.venv\Scripts\activate
python -m tools.check_camera
.\run-camera.cmd 0
```

If `check_camera` cannot find the webcam, open the Windows Camera app first and make sure camera access is enabled under Windows Settings > Privacy & security > Camera.

## Hardware Profiles

The edge process uses named profiles to tune capture resolution, detector cadence, live-preview cost, and OCR budget together.

- `workstation_track` - default USB laptop/workstation profile for smoother tracking.
- `gpu_detail` - higher-resolution profile when GPU power is available.
- `sharp_read` - plate-detail priority.
- `fast_lane` - higher motion cadence.
- `track_boost` - lower-resolution, high-cadence tracking.
- `night_boost` - lower light / IR conditions.
- `edge_economy` - constrained hardware or heat-sensitive installs.

Override profiles with:

```powershell
set EISENFIEDER_SOURCE__QUALITY_PROFILE=workstation_track
```

## Tracking Model

The detector can use YOLO/ByteTrack IDs when available. EisenFieder also applies a local stabilizer that bridges short occlusions, missed detections, and tracker ID churn with box prediction and IOU/center matching. Important knobs:

- `EISENFIEDER_DETECTOR__STABILIZER_MAX_MISSING`
- `EISENFIEDER_DETECTOR__STABILIZER_MIN_IOU`
- `EISENFIEDER_DETECTOR__STABILIZER_MAX_CENTER_DIST_FRAC`
- `EISENFIEDER_DETECTOR__STABILIZER_SMOOTH`
- `EISENFIEDER_EVENTS__TRACK_MISS_GRACE`
- `EISENFIEDER_EVENTS__TRACK_MIN_FRAMES`
- `EISENFIEDER_EVENTS__TRACK_MAX_AGE_SECONDS`

Parked vehicles are filtered by movement/approach gates, so a stationary vehicle is not repeatedly logged when detections flicker.

## Tests

```powershell
cd edge
python tests/test_edge.py

cd ..\backend
python tests/test_api.py

cd ..\dashboard
npm run build
```

## Production Notes

Before a real install:

- Set a strong `OWNER_PASSWORD`.
- Set a random 32+ character `JWT_SECRET`.
- Register each camera and use per-camera pairing tokens.
- Keep `.env`, databases, media, logs, and model weights out of GitHub.
- Decide retention with `DATA_RETENTION_DAYS`.

All footage and plate records remain local unless you explicitly add external integrations.
