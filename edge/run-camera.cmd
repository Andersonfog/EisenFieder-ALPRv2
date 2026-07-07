@echo off
REM Runs the camera in REAL mode against the local backend:
REM   * real vehicle detection (YOLO) from the USB webcam,
REM   * real license-plate OCR (fast-alpr), real colour from pixels,
REM   * live preview streamed to the console.
REM No fake data: plates/colour come from what the camera actually sees.
REM (First run downloads the AI models once, then they're cached.)
set "BACKEND_URL=http://127.0.0.1:8000"
set "EISENFIEDER_CAMERA__ID=EFS-DEMO-001"
set "EISENFIEDER_CAMERA__NAME=USB ALPR Camera"
set "EISENFIEDER_CAMERA__LOCATION=Front entrance"
set "EISENFIEDER_SOURCE__BACKEND=usb"
set "EISENFIEDER_SOURCE__USB_INDEX=0"
set "EISENFIEDER_SOURCE__QUALITY_PROFILE=track_boost"
set "EISENFIEDER_EVENTS__PROVISIONAL_EVENTS=false"
set "EISENFIEDER_UPLOADER__ENABLED=true"
set "EISENFIEDER_UPLOADER__LIVE_ENABLED=true"
set "EISENFIEDER_UPLOADER__LIVE_FPS=30"
set "EISENFIEDER_UPLOADER__LIVE_MAX_WIDTH=960"
set "EISENFIEDER_UPLOADER__LIVE_JPEG_QUALITY=72"
REM Detect at 320px: cars are big objects, so accuracy barely moves but the
REM detector runs ~40%% faster — and plates are read from the FULL-RES frame
REM anyway. More detector speed = smoother tracking AND a smoother live view
REM (the CPU it frees goes to capture/encode/upload).
set "EISENFIEDER_DETECTOR__IMGSZ=320"
set "EISENFIEDER_DETECTOR__MAX_DET=10"
set "EISENFIEDER_DETECTOR__CONFIDENCE_THRESHOLD=0.40"
set "EISENFIEDER_DETECTOR__AGNOSTIC_NMS=true"
set "EISENFIEDER_DETECTOR__TRACK=false"
python -m efsurveillance.main --source usb --backend yolo
