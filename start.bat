@echo off

chcp 65001 >nul

cd /d "%~dp0"

echo ══════════════════════════════════════════════════════════════

echo   Vaccination Game - Server starten

echo ══════════════════════════════════════════════════════════════

echo.

:: --- Check embedded Python ---

set "PYTHON=%~dp0python\python.exe"

if not exist "%PYTHON%" (

    echo [FEHLER] Python nicht gefunden!

    echo Bitte fuehren Sie zuerst setup.bat aus.

    goto :end

)

:: --- Check if dependencies installed ---

"%PYTHON%" -c "import flask" 2>nul

if errorlevel 1 (

    echo [FEHLER] Abhaengigkeiten nicht installiert!

    echo Bitte fuehren Sie zuerst setup.bat aus.

    goto :end

)

:: --- Generate secrets ---

echo [1/4] Generiere Passwoerter...

"%PYTHON%" -c "import secrets; print(secrets.token_urlsafe(48))" > _tmp_secret.txt

set /p SECRET_KEY=<_tmp_secret.txt

del _tmp_secret.txt

"%PYTHON%" -c "import secrets; print(secrets.token_urlsafe(16))" > _tmp_admin.txt

set /p ADMIN_PASSWORD=<_tmp_admin.txt

del _tmp_admin.txt


set FLASK_ENV=production

set FLASK_DEBUG=0

set PORT=8000

set THREADS=48

:: --- Start server ---

echo [2/4] Starte Server...

start /b "" "%PYTHON%" "%~dp0serve_waitress.py"

:: --- Wait for health check ---

echo [3/4] Warte auf Server...

set HEALTHY=0

for /L %%i in (1,1,30) do (

    timeout /t 1 /nobreak >nul

    powershell -Command "try { $r = Invoke-WebRequest -Uri 'http://127.0.0.1:%PORT%/healthz' -UseBasicParsing -TimeoutSec 2; if($r.StatusCode -eq 200) { exit 0 } } catch { exit 1 }" 2>nul

    if not errorlevel 1 (

        set HEALTHY=1

        goto :server_ready

    )

)

:server_ready

 

if "%HEALTHY%"=="0" (

    echo [FEHLER] Server konnte nicht gestartet werden.

    echo Pruefe ob Port %PORT% bereits belegt ist.

    goto :end

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

set "PUBLIC_URL="

for /L %%i in (1,1,45) do (

    timeout /t 2 /nobreak >nul

    for /f "tokens=*" %%a in ('powershell -Command "if(Test-Path cloudflared.log){Select-String -Path cloudflared.log -Pattern 'https://[a-z0-9-]+\.trycloudflare\.com' | Select-Object -First 1 | ForEach-Object { $_.Matches[0].Value }}"') do set "PUBLIC_URL=%%a"

    if defined PUBLIC_URL goto :tunnel_ready

)

:tunnel_ready

 

echo.

echo ══════════════════════════════════════════════════════════════

if defined PUBLIC_URL (

    echo   OEFFENTLICHER LINK:

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

echo.

echo   ADMIN-PASSWORT: %ADMIN_PASSWORD%

echo ══════════════════════════════════════════════════════════════

echo.

echo   Server laeuft.

echo   Zum Beenden: "close server" eingeben oder Fenster schliessen

echo.

 

:: --- Command loop ---

:cmd_loop

set "CMD="

set /p "CMD=> "

if /i "%CMD%"=="close server" goto :shutdown

echo   Unbekannter Befehl. Zum Beenden: "close server"

goto :cmd_loop

 

:shutdown

echo.

echo Fahre Server herunter...

 

:: Stop cloudflared

taskkill /f /im cloudflared.exe >nul 2>&1

echo   Cloudflare Tunnel beendet.

 

:: Stop Python server

for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%PORT%.*LISTENING"') do taskkill /f /pid %%a >nul 2>&1

echo   Server beendet.

 

echo.

echo Server wurde ordnungsgemaess beendet.

echo Dieses Fenster kann jetzt geschlossen werden.
 
:end

echo.

pause