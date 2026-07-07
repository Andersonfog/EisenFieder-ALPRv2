@echo off
setlocal
REM Runs the camera in REAL USB mode against the local backend.
REM Usage:
REM   run-camera.cmd           uses USB camera index 0
REM   run-camera.cmd 1         uses USB camera index 1
REM   run-camera.cmd 1 EFS-USB-SIDE  uses camera index 1 and a custom camera id

cd /d "%~dp0"
if exist "..\.venv\Scripts\activate.bat" call "..\.venv\Scripts\activate.bat"

set "USB_INDEX=%~1"
if "%USB_INDEX%"=="" set "USB_INDEX=0"
set "CAMERA_ID=%~2"
if "%CAMERA_ID%"=="" set "CAMERA_ID=EFS-USB-001"

python -c "import cv2, ultralytics, fast_alpr" >nul 2>nul
if errorlevel 1 (
  echo.
  echo Missing USB/AI dependencies.
  echo From the repository root, run:
  echo   install-usb.cmd
  echo.
  exit /b 1
)

python -m tools.check_camera --index %USB_INDEX%
if errorlevel 1 exit /b 1

REM Dev/local defaults. In production, register the camera in the console and
REM put BACKEND_API_TOKEN in edge\.env instead of relying on open local ingest.
set "BACKEND_URL=http://127.0.0.1:8000"
set "EISENFIEDER_CAMERA__ID=%CAMERA_ID%"
set "EISENFIEDER_CAMERA__NAME=USB ALPR Camera"
set "EISENFIEDER_CAMERA__LOCATION=Front entrance"
set "EISENFIEDER_SOURCE__BACKEND=usb"
set "EISENFIEDER_SOURCE__USB_INDEX=%USB_INDEX%"
set "EISENFIEDER_SOURCE__QUALITY_PROFILE=workstation_track"
set "EISENFIEDER_EVENTS__PROVISIONAL_EVENTS=false"
set "EISENFIEDER_UPLOADER__ENABLED=true"
set "EISENFIEDER_UPLOADER__LIVE_ENABLED=true"
set "EISENFIEDER_UPLOADER__LIVE_MODE=stream"
set "EISENFIEDER_UPLOADER__LIVE_FPS=30"
set "EISENFIEDER_UPLOADER__LIVE_MAX_WIDTH=1280"
set "EISENFIEDER_UPLOADER__LIVE_JPEG_QUALITY=76"

REM Laptop/workstation defaults: keep real YOLO tracking on, then let the
REM local stabilizer bridge short occlusions or tracker id churn.
set "EISENFIEDER_DETECTOR__BACKEND=yolo"
set "EISENFIEDER_DETECTOR__DEVICE=cpu"
set "EISENFIEDER_DETECTOR__IMGSZ=640"
set "EISENFIEDER_DETECTOR__MAX_DET=20"
set "EISENFIEDER_DETECTOR__CONFIDENCE_THRESHOLD=0.35"
set "EISENFIEDER_DETECTOR__AGNOSTIC_NMS=true"
set "EISENFIEDER_DETECTOR__TRACK=true"
set "EISENFIEDER_DETECTOR__STABILIZER_MAX_MISSING=120"
set "EISENFIEDER_EVENTS__TRACK_MISS_GRACE=90"

echo.
echo Starting USB ALPR camera %CAMERA_ID% on webcam index %USB_INDEX%.
echo Backend: %BACKEND_URL%
echo.
python -m efsurveillance.main --source usb --backend yolo
