@echo off
setlocal
cd /d "%~dp0"
if exist "..\.venv\Scripts\activate.bat" call "..\.venv\Scripts\activate.bat"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
