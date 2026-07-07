@echo off
REM EisenFieder Surveillance - one-click local demo launcher.
REM Double-click this file. It opens two windows (backend + console) that STAY
REM open, then opens the console in your browser.

echo Starting EisenFieder Surveillance...

REM /D sets each window's working directory (quoted, so the space in the folder
REM name is handled correctly). cmd /k keeps the window open and running.
start "EisenFieder Backend" /D "%~dp0backend"   cmd /k "python -m uvicorn app.main:app --port 8000"
start "EisenFieder Console" /D "%~dp0dashboard"  cmd /k "npm run dev"

REM Wait for the backend, then start a mock camera so live annotated vehicles
REM (plate + make/model) stream into the console.
timeout /t 5 >nul
start "EisenFieder Camera (mock)" /D "%~dp0edge"  cmd /k "run-camera.cmd"

REM Give everything a moment, then open the browser on the address that always
REM works (loopback, not the LAN IP).
timeout /t 4 >nul
start http://127.0.0.1:5174

echo.
echo Three windows opened (backend, console, mock camera).
echo Log in at http://127.0.0.1:5174
echo   email:    owner@eisenfieder.local
echo   password: changeme123
echo.
echo New vehicles with annotated images appear in the Vehicle Log as the camera
echo runs. Close those three windows to stop the demo.
