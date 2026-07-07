@echo off
REM Runs the camera in REAL mode against the local backend:
REM   * real vehicle detection (YOLO) from the USB webcam,
REM   * real license-plate OCR (fast-alpr), real colour from pixels,
REM   * live preview streamed to the console.
REM No fake data: plates/colour come from what the camera actually sees.
REM First run downloads the AI models once, then caches them.
set "BACKEND_URL=http://127.0.0.1:8000"
set "EISENFIEDER_CAMERA__ID=EFS-DEMO-001"
set "EISENFIEDER_CAMERA__NAME=USB ALPR Camera"
set "EISENFIEDER_CAMERA__LOCATION=Front entrance"
set "EISENFIEDER_SOURCE__BACKEND=usb"
set "EISENFIEDER_SOURCE__USB_INDEX=0"
set "EISENFIEDER_SOURCE__QUALITY_PROFILE=workstation_track"
set "EISENFIEDER_EVENTS__PROVISIONAL_EVENTS=false"
set "EISENFIEDER_UPLOADER__ENABLED=true"
set "EISENFIEDER_UPLOADER__LIVE_ENABLED=true"
set "EISENFIEDER_UPLOADER__LIVE_FPS=30"
set "EISENFIEDER_UPLOADER__LIVE_MAX_WIDTH=1280"
set "EISENFIEDER_UPLOADER__LIVE_JPEG_QUALITY=76"
REM Laptop/workstation defaults: keep real YOLO tracking on, then let the
REM local stabilizer bridge short occlusions or tracker id churn.
set "EISENFIEDER_DETECTOR__IMGSZ=640"
set "EISENFIEDER_DETECTOR__MAX_DET=20"
set "EISENFIEDER_DETECTOR__CONFIDENCE_THRESHOLD=0.35"
set "EISENFIEDER_DETECTOR__AGNOSTIC_NMS=true"
set "EISENFIEDER_DETECTOR__TRACK=true"
set "EISENFIEDER_DETECTOR__STABILIZER_MAX_MISSING=120"
set "EISENFIEDER_EVENTS__TRACK_MISS_GRACE=90"
python -m efsurveillance.main --source usb --backend yolo
