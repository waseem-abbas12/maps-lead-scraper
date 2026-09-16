@echo off
title Maps Lead Scraper - Online Live Share
echo ============================================================
echo       Maps Lead Scraper - Starting Web Server & Live URL...
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
echo [2/2] Detecting public IP and starting secure online link...
for /f "usebackq tokens=*" %%i in (`powershell -NoProfile -Command "(Invoke-RestMethod -Uri https://api.ipify.org)"`) do set "MY_IP=%%i"

echo.
echo ============================================================
echo  SHARE THIS INFORMATION WITH YOUR CLIENT / USER:
echo  1. Copy the public https://....loca.lt URL shown below
echo  2. If it asks for "Tunnel Password" / "Endpoint IP", enter: %MY_IP%
echo  3. Invitation Code: LEAD-PRO-2026
echo ============================================================
echo.
npx localtunnel --port 8000
pause
