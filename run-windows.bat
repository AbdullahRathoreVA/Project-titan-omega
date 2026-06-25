@echo off
REM ============================================================
REM  Titan Omega - one-click local run for Windows
REM  Needs Python (python.org) and Node.js (nodejs.org) installed.
REM  Double-click this file. Two windows open; your browser opens
REM  the dashboard at http://localhost:3000. Close the windows to stop.
REM ============================================================

echo Starting Titan Omega...

REM --- Backend (Executive Intelligence Core) on port 8000 ---
start "Titan Core" cmd /k "cd /d "%~dp0backend" && pip install -r requirements.txt && uvicorn app.main:app --port 8000"

REM --- Frontend (Empire Command Center) on port 3000 ---
start "Titan Dashboard" cmd /k "cd /d "%~dp0frontend" && npm install && npm run dev"

REM --- Give them a moment, then open the browser ---
timeout /t 12 /nobreak >nul
start "" http://localhost:3000

echo.
echo Titan Omega is starting. The dashboard will open in your browser.
echo Local run needs no login. Close the two windows to stop everything.
