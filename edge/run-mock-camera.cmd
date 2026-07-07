@echo off
setlocal
REM Runs the synthetic/mock camera for demos without a webcam or AI packages.

cd /d "%~dp0"
if exist "..\.venv\Scripts\activate.bat" call "..\.venv\Scripts\activate.bat"

set "BACKEND_URL=http://127.0.0.1:8000"
set "EISENFIEDER_CAMERA__ID=EFS-MOCK-001"
set "EISENFIEDER_CAMERA__NAME=Mock Demo Camera"
set "EISENFIEDER_CAMERA__LOCATION=Demo entrance"
set "EISENFIEDER_SOURCE__BACKEND=synthetic"
set "EISENFIEDER_DETECTOR__BACKEND=mock"
set "EISENFIEDER_UPLOADER__ENABLED=true"
set "EISENFIEDER_UPLOADER__LIVE_ENABLED=true"
set "EISENFIEDER_UPLOADER__LIVE_MODE=stream"

python -m efsurveillance.main --source synthetic --backend mock
