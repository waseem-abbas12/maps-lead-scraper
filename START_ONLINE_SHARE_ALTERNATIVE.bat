@echo off
title Maps Lead Scraper - Online Share (Alternative)
echo ============================================================
echo       Maps Lead Scraper - Starting Alternative Live Tunnel
echo ============================================================
echo.

:: Check if server is already running on port 8000
netstat -ano | findstr :8000 >nul
if %errorlevel% neq 0 (
    echo [1/2] Starting backend server on port 8000...
    start /min python server.py
    timeout /t 3 /nobreak >nul
) else (
    echo [1/2] Backend server already running on port 8000!
)

echo.
echo [2/2] Generating 100% Working Live Link...
echo.
echo ============================================================
echo  SHARE THE https://....lhr.life LINK SHOWN BELOW WITH YOUR FRIEND:
echo  (NOTE: Keep this window OPEN on your PC while they use it!)
echo ============================================================
echo.
ssh -o StrictHostKeyChecking=no -R 80:localhost:8000 nokey@localhost.run
pause
