@echo off
setlocal
cd /d "%~dp0"

set "USB_INDEX=%~1"
if "%USB_INDEX%"=="" set "USB_INDEX=0"
set "CAMERA_ID=%~2"
if "%CAMERA_ID%"=="" set "CAMERA_ID=EFS-USB-001"

if not exist ".venv\Scripts\python.exe" (
  echo Missing .venv. Run install-usb.cmd first.
  echo.
  pause
  exit /b 1
)

echo Starting EisenFieder ALPR USB stack...
echo Camera index: %USB_INDEX%
echo Camera id:    %CAMERA_ID%
echo.

start "EisenFieder Backend" /D "%~dp0backend" cmd /k "run-dev.cmd"
start "EisenFieder Dashboard" /D "%~dp0dashboard" cmd /k "run-dev.cmd"

timeout /t 6 >nul
start "EisenFieder USB Camera" /D "%~dp0edge" cmd /k "run-camera.cmd %USB_INDEX% %CAMERA_ID%"

timeout /t 4 >nul
start http://127.0.0.1:5174

echo Opened backend, dashboard, and USB camera windows.
echo Login: owner@eisenfieder.local / changeme123
echo Close the three windows to stop.
