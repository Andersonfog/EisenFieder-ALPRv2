# EisenFieder Surveillance

A **single-tenant entrance camera system** for small businesses. Detects every vehicle, reads the license plate, logs make/color/type/occupants/company branding, and stores one still per event — all on-premises, owner-only access.

- **Real-time detection** (YOLO v8n)
- **Plate OCR** (fast-alpr)
- **Web console** for search, watchlist, live preview, analytics
- **SQLite backend** (no cloud, no external APIs)
- **Single owner login** — footage is private by design

---

## Quick Start (Raspberry Pi 5)

### Hardware

- Raspberry Pi 5 (4GB+ RAM recommended; 8GB for smooth YOLO)
- USB camera or CSI/MIPI camera (e.g., Arducam OV5647)
- microSD card (32GB+; class 10 for live preview smoothness)
- Ethernet or WiFi (for connecting from your phone/laptop to the console)

### Setup (15 min)

1. **Flash Raspberry Pi OS (Bookworm, 64-bit)** to the microSD card using Raspberry Pi Imager.

2. **Boot, connect to WiFi, open terminal.**

3. **Clone the repo:**
   ```bash
   cd ~
   git clone https://github.com/your-org/eisenfieder-surveillance.git
   cd eisenfieder-surveillance
   ```

4. **Run the installer** (handles Python, system deps, ML models):
   ```bash
   sudo bash edge/install-pi.sh
   ```

5. **Configure** (edit `edge/config.yaml`):
   ```yaml
   camera:
     id: EFS-PI-001
     name: "Front Gate"
     location: "North entrance"
   
   source:
     backend: usb  # or picamera2 for CSI cameras
     device_index: 0
   
   uploader:
     backend_url: http://your-laptop-ip:8000
   ```

6. **Start the system:**
   ```bash
   python -m efsurveillance.main
   ```

7. **Open the console** on your laptop/phone at `http://pi-ip:5174` (e.g., `http://192.168.1.42:5174`).
   - Login: `owner@eisenfieder.local` / `changeme123`
   - Go to **Cameras** → **Register** → enter Pi's serial (e.g., `EFS-PI-001`)
   - Copy the env snippet and update `edge/config.yaml` with the pairing token

8. **Watch live preview** in the **Live View** tab and **Vehicle Log** to see detected cars.

---

## Full Setup Guide

### 1. Backend (Server, runs on Pi or laptop)

The backend stores events, serves the web console, and handles owner login.

**On the Pi or on a separate server machine:**

```bash
cd backend
pip install -r requirements.txt
python -m scripts.seed_demo        # Optional: load demo data
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

The backend listens on all interfaces (`0.0.0.0:8000`). Point your console at it using the **Pi's local IP** (find via `hostname -I`).

**Environment:**
- `APP_ENV=production` — refuse weak secrets, require pairing tokens
- `BUSINESS_NAME` — shown in the console
- `OWNER_EMAIL` / `OWNER_PASSWORD` — the only human login
- `DATABASE_URL` — defaults to `sqlite:///./surveillance.db` (local file)
- `JWT_SECRET` — random 32+ chars in production
- `INGEST_TOKEN` — camera auth fallback (optional if using per-device tokens)

All defaults work for local demo; `.env.example` has the full list.

### 2. Edge (Camera, runs on Pi)

The edge unit captures frames, detects vehicles, reads plates, and uploads events to the backend.

**On the Pi:**

```bash
cd edge
pip install -r requirements-pi.txt  # ML models + Pi-specific libs
python -m efsurveillance.main --config config.yaml
```

**First run:** downloads YOLO + fast-alpr + easyocr models (~2GB, one-time).

**Configuration** (`edge/config.yaml`):
```yaml
camera:
  id: EFS-PI-001          # Must match the serial you register in the console
  name: "North entrance"
  location: "Driveway"

source:
  backend: picamera2      # CSI/MIPI camera; use "usb" for USB
  picamera_index: 0
  width: 1920
  height: 1080
  process_fps: 4          # Detection loop rate (YOLO is slow; 4 fps is ~normal for Pi5)

detector:
  backend: yolo           # "mock" for laptop demo without ML
  confidence_threshold: 0.5
  model_path: ./yolov8n.pt
  device: cpu             # Use "cuda" if you have NVIDIA GPU

uploader:
  backend_url: http://192.168.1.50:8000   # Your backend's IP:port
  live_enabled: true
  live_fps: 4                              # Preview frame rate
  live_max_width: 640
```

**Check the camera first:**
```bash
python edge/tools/check_camera.py
# Opens the camera, shows resolution, checks permissions.
# If this fails, the main loop will fail too.
```

### 3. Console (Web UI, runs on your laptop)

The console is a React/Vite app that talks to the backend.

**On your laptop:**

```bash
cd dashboard
npm install
npm run dev
# Opens on http://localhost:5174
```

Point it at your Pi's backend (the console auto-discovers if you use localhost, but for Pi access set `VITE_API_BASE` in `.env.local`):
```bash
# .env.local
VITE_API_BASE=http://192.168.1.42:8000
```

**Features:**
- **Overview** — total vehicles, 24h count, flagged alerts, distribution chart
- **Live View** — real-time camera preview (FPS meter)
- **Vehicle Log** — search by plate, make, color, company, direction, time range
- **Watchlist** — flag license plates for SMS alerts (Twilio integration optional)
- **Cameras** — register new units, manage pairing tokens, set per-camera filters
- **Insights** — hourly/daily traffic trends, returning vehicles, commercial fleets

---

## Registration & Auth

**Backend → Camera pairing:**

1. Pi starts with `id: EFS-PI-001` (from config.yaml).
2. In the console, go to **Cameras** → **Register**.
3. Enter the serial (`EFS-PI-001`), name, location.
4. Console generates a **one-time pairing token** and prints an `.env` snippet.
5. Copy the `BACKEND_API_TOKEN` into `edge/config.yaml` or export it before running the edge process.
6. Edge unit now authenticated: ingest and live-preview requests include the token.

**Console → Backend:**

- Single owner login via email + password (default: `owner@eisenfieder.local` / `changeme123`).
- Backend issues a JWT; console stores it in browser local storage.
- All API requests include the JWT bearer token.
- No cookies; CORS is allowed only for your registered console origin.

---

## Troubleshooting

### "Camera not found"

**On the Pi:**
```bash
python edge/tools/check_camera.py
```

If it fails:
- Confirm the camera is plugged in (USB) or enabled (CSI via `raspi-config`).
- Check permissions: `sudo usermod -aG video $USER` (then reboot).
- Try different device index: `source.device_index: 1` in config.

### "Backend URL unreachable"

- Confirm the backend is running: `netstat -tuln | grep 8000` (on the server).
- Use the server's **local IP**, not `localhost`:
  ```bash
  # On the server (Pi or laptop):
  hostname -I
  # Example output: 192.168.1.50 10.150.134.247
  # Use 192.168.1.50:8000 in config.yaml
  ```

### "Invalid pairing token"

- Confirm the token in `config.yaml` matches the one printed by the console during registration.
- Tokens are **case-sensitive** and **one-time**: if lost, regenerate via **Cameras → KEY**.

### "YOLO / Plate OCR slow"

- Pi 5 with CPU inference runs ~3–4 fps. Normal.
- For faster detection (10+ fps), add a **Coral TPU** (`edgetpu.dev`) or **NVIDIA GPU** (not practical on Pi).
- Reduce `source.width/height` in config to speed up inference.

### "Database locked"

- SQLite can have lock contention if multiple processes write at once.
- Edge and backend should **not run on the same process**; use separate machines or separate processes.
- If you must run both on the same Pi, enable WAL mode (backend does this automatically).

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│ Raspberry Pi 5                                          │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  Edge Unit (Python, efsurveillance/)                   │
│  ├─ Capture (camera thread, 30 fps)                    │
│  ├─ Detect (YOLO, ~4 fps)                              │
│  ├─ Read plate (fast-alpr)                             │
│  ├─ Recognize (make/color/occupants/company)           │
│  ├─ Live preview (JPEG push to backend every 250ms)   │
│  └─ Upload events (vehicle_events table via HTTP POST) │
│                                                          │
│  ↓ (HTTP POST /api/v1/vehicles, X-Camera-Id header)    │
│                                                          │
│  Backend (FastAPI, app/)                               │
│  ├─ User auth (JWT, owner-only console login)          │
│  ├─ Camera auth (pairing token, ingest + live frames)  │
│  ├─ SQLite DB (vehicle_events, watchlist, cameras)     │
│  ├─ Event storage (MEDIA_DIR, owner-only access)       │
│  └─ API (GET /vehicles, /stats, /analytics, etc)       │
│                                                          │
└─────────────────────────────────────────────────────────┘
                         ↑
                    (HTTP REST)
                         ↓
        Your Laptop (console, port 5174)
        ├─ React/Vite web app
        ├─ Search, live preview, watchlist
        └─ Analytics dashboard
```

**Data flow:**
1. **Camera** → capture frames
2. **Edge** → detect + recognize + upload `POST /api/v1/vehicles`
3. **Backend** → store in SQLite + media folder
4. **Console** → fetch via `GET /api/v1/vehicles` (JWT auth)
5. **Console** → fetch stills via `GET /api/v1/media/{key}` (JWT auth)

All footage stays on-premises. No cloud. No external APIs (except optional Twilio for SMS alerts).

---

## Performance Notes

**Raspberry Pi 5 + YOLO (CPU):**
- Capture: ~30 fps (limited by camera and USB bandwidth)
- Detect: ~3–4 fps (YOLO inference)
- Upload: negligible (async, best-effort)
- Live preview: ~4 fps (pushed every 250ms)
- Console polling: ~1 fps (but streams show live preview via held-open MJPEG)

**To improve:**
- **GPU:** Add a Coral TPU (~10x faster detection) or NVIDIA Jetson (overkill for Pi).
- **Lighter model:** YOLO has nano/small variants; trade accuracy for speed.
- **Lower resolution:** 1280×720 instead of 1920×1080 reduces inference time.
- **Async uploader:** Images are uploaded in a background thread (already done).

**Database:**
- SQLite with WAL mode (Pi backend enables this by default).
- Composite index on `(camera_id, captured_at)` for log queries.
- Typical: ~500 KB per vehicle event (event record + 30–50 KB JPEG).
- Retention: configurable via `DATA_RETENTION_DAYS` and `scripts/purge_old.py`.

---

## Development

### Running locally (laptop, no real camera)

Mock backend (no ML):
```bash
cd backend
python -m scripts.seed_demo      # Load demo data
python -m uvicorn app.main:app --reload
```

Mock edge (synthetic video):
```bash
cd edge
python -m efsurveillance.main --backend mock --source synthetic
```

Console:
```bash
cd dashboard
npm run dev
```

Access: `http://localhost:5174` (no real camera, just demo events).

### Running tests

```bash
cd backend
python tests/test_api.py         # 12 tests, no dependencies

cd ../edge
python tests/test_edge.py        # 12 tests, no ML models
```

### Building for production

```bash
# Minimize the console bundle
cd dashboard
npm run build
# Outputs: dist/ (static HTML/CSS/JS)
# Serve via: python -m http.server --directory dist 5174

# Secure config for production
APP_ENV=production \
JWT_SECRET=$(openssl rand -hex 32) \
OWNER_PASSWORD=$(openssl rand -hex 16) \
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

---

## Security model (the whole point)

- **One login, one owner.** There is a single business-owner account. Nobody else can read the data.
- **Footage is never public.** Captured images are served *only* through an authenticated endpoint (`/api/v1/media/...`). There is no public media folder, so stills can't be opened by guessing a URL.
- **Cameras authenticate too.** Each camera is registered by serial number and gets a one-time pairing token it must present to upload — no token, no ingest.
- **Hardening built in.** PBKDF2 password hashing, signed JWT sessions, login brute-force limiter, browser security headers, upload size caps, and a production boot-check that refuses to start with weak secrets.
- **Privacy retention.** Optional auto-purge of records/images older than `DATA_RETENTION_DAYS` (see `backend/scripts/purge_old.py`).

---

## Next steps

- **Make/model classifier:** Stub in `recognizer.py` — needs a trained ONNX model.
- **Company OCR:** Use `easyocr` to read text on vehicle sides; framework ready, not yet wired.
- **Twilio SMS:** Set `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER`, `OWNER_PHONE` to get SMS alerts on watchlist hits.
- **Multi-camera:** Register multiple Pi units; each gets a unique serial and pairing token. Console filters by camera.

Happy surveilling! 🚗📷
