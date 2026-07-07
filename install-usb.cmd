@echo off
setlocal
cd /d "%~dp0"

set "PYTHON_CMD=python"
where python >nul 2>nul
if errorlevel 1 (
  where py >nul 2>nul
  if errorlevel 1 (
    echo Python was not found. Install Python 3.11+ and check "Add python.exe to PATH".
    exit /b 1
  )
  set "PYTHON_CMD=py -3"
)

if not exist ".venv\Scripts\python.exe" (
  echo Creating .venv...
  %PYTHON_CMD% -m venv .venv
  if errorlevel 1 exit /b 1
)

call ".venv\Scripts\activate.bat"
python -m pip install --upgrade pip
python -m pip install -r backend\requirements.txt
if errorlevel 1 exit /b 1
python -m pip install -r edge\requirements-usb.txt
if errorlevel 1 exit /b 1

where npm >nul 2>nul
if errorlevel 1 (
  echo.
  echo Node.js/npm was not found. Install Node.js LTS, then run install-usb.cmd again.
  exit /b 1
)

pushd dashboard
if not exist node_modules npm install
popd

echo.
echo USB camera install complete.
echo Next:
echo   start-usb-camera.cmd
echo.
pause
