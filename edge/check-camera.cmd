@echo off
REM Double-click to check whether your webcam works before running the trial.
cd /d "%~dp0"
if exist "..\.venv\Scripts\activate.bat" call "..\.venv\Scripts\activate.bat"
python -m tools.check_camera %*
echo.
pause
