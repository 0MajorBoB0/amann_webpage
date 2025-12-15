@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion

cd /d "%~dp0"

echo ══════════════════════════════════════════════════════════════
echo   Impfspiel - Server starten
echo ══════════════════════════════════════════════════════════════
echo.

:: --- Check embedded Python ---
set PYTHON=%~dp0python\python.exe
if not exist "%PYTHON%" (
    echo [FEHLER] Python nicht gefunden!
    echo Bitte fuehren Sie zuerst setup.bat aus.
    pause
    exit /b 1
)

:: --- Check if dependencies installed ---
"%PYTHON%" -c "import flask" 2>nul
if errorlevel 1 (
    echo [FEHLER] Abhaengigkeiten nicht installiert!
    echo Bitte fuehren Sie zuerst setup.bat aus.
    pause
    exit /b 1
)

:: --- Generate secrets ---
echo [1/4] Generiere Passwoerter...
for /f %%i in ('"%PYTHON%" -c "import secrets; print(secrets.token_urlsafe(48))"') do set SECRET_KEY=%%i
for /f %%i in ('"%PYTHON%" -c "import secrets; print(secrets.token_urlsafe(16))"') do set ADMIN_PASSWORD=%%i

set FLASK_ENV=production
set FLASK_DEBUG=0
set PORT=8000
set THREADS=32

echo.
echo ══════════════════════════════════════════════════════════════
echo   ADMIN-PASSWORT (nur fuer diesen Serverstart):
echo   %ADMIN_PASSWORD%
echo ══════════════════════════════════════════════════════════════
echo.

:: --- Start server ---
echo [2/4] Starte Server...
start /b "" "%PYTHON%" serve_waitress.py

:: --- Wait for health check ---
echo [3/4] Warte auf Server...
set HEALTHY=0
for /L %%i in (1,1,30) do (
    timeout /t 1 /nobreak >nul
    powershell -Command "(Invoke-WebRequest -Uri 'http://127.0.0.1:%PORT%/healthz' -UseBasicParsing -TimeoutSec 2).StatusCode" 2>nul | findstr "200" >nul
    if not errorlevel 1 (
        set HEALTHY=1
        goto :server_ready
    )
)
:server_ready

if "%HEALTHY%"=="0" (
    echo [FEHLER] Server konnte nicht gestartet werden.
    pause
    exit /b 1
)
echo       Server laeuft auf http://127.0.0.1:%PORT%

:: --- Cloudflared ---
echo [4/4] Starte Cloudflare Tunnel...

if not exist "cloudflared.exe" (
    echo       Lade cloudflared.exe herunter...
    powershell -Command "Invoke-WebRequest -Uri 'https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe' -OutFile 'cloudflared.exe'"
)

:: Kill old tunnel
taskkill /f /im cloudflared.exe >nul 2>&1
timeout /t 1 /nobreak >nul

:: Start tunnel
start /b "" cloudflared.exe tunnel --url http://127.0.0.1:%PORT% --protocol http2 --no-autoupdate 2>cloudflared.log

:: Wait for public URL
echo       Warte auf oeffentliche URL...
set PUBLIC_URL=
for /L %%i in (1,1,45) do (
    timeout /t 2 /nobreak >nul
    for /f "tokens=*" %%a in ('powershell -Command "Select-String -Path 'cloudflared.log' -Pattern 'https://[a-z0-9-]+\.trycloudflare\.com' | Select-Object -First 1 | ForEach-Object { $_.Matches[0].Value }"') do set PUBLIC_URL=%%a
    if defined PUBLIC_URL goto :tunnel_ready
)
:tunnel_ready

echo.
echo ══════════════════════════════════════════════════════════════
if defined PUBLIC_URL (
    echo   OEFFENTLICHER LINK (fuer Teilnehmer):
    echo   %PUBLIC_URL%
    echo.
    echo   ADMIN-BEREICH:
    echo   %PUBLIC_URL%/admin
) else (
    echo   Tunnel-URL konnte nicht ermittelt werden.
    echo   Siehe cloudflared.log
)
echo.
echo   LOKAL: http://127.0.0.1:%PORT%
echo   ADMIN: http://127.0.0.1:%PORT%/admin
echo.
echo   ADMIN-PASSWORT: %ADMIN_PASSWORD%
echo ══════════════════════════════════════════════════════════════
echo.
echo   Server laeuft. Dieses Fenster NICHT schliessen!
echo   Zum Beenden: Fenster schliessen oder STRG+C
echo.

:: Keep window open
cmd /k
