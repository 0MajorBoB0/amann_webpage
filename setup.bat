@echo off
chcp 65001 >nul
setlocal

echo ══════════════════════════════════════════════════════════════
echo   Impfspiel - Ersteinrichtung
echo ══════════════════════════════════════════════════════════════
echo.

cd /d "%~dp0"

:: --- Check if python folder exists ---
if not exist "python\python.exe" (
    echo [FEHLER] Ordner "python" mit Python Embedded nicht gefunden!
    echo.
    echo Bitte laden Sie Python Embedded herunter:
    echo   https://www.python.org/ftp/python/3.12.7/python-3.12.7-embed-amd64.zip
    echo.
    echo Entpacken Sie den Inhalt in einen Ordner namens "python" hier.
    echo.
    pause
    exit /b 1
)

set PYTHON=%~dp0python\python.exe
set PIP=%~dp0python\Scripts\pip.exe

:: --- Enable site-packages in embedded Python ---
echo [1/4] Aktiviere site-packages...
set PTH_FILE=%~dp0python\python312._pth
if exist "%PTH_FILE%" (
    findstr /C:"import site" "%PTH_FILE%" >nul 2>&1
    if errorlevel 1 (
        echo import site>> "%PTH_FILE%"
        echo       site-packages aktiviert.
    ) else (
        echo       bereits aktiviert.
    )
)

:: --- Download get-pip.py if needed ---
if not exist "%PIP%" (
    echo [2/4] Lade pip herunter...
    if not exist "get-pip.py" (
        powershell -Command "Invoke-WebRequest -Uri 'https://bootstrap.pypa.io/get-pip.py' -OutFile 'get-pip.py'"
    )
    "%PYTHON%" get-pip.py --no-warn-script-location
    del get-pip.py 2>nul
) else (
    echo [2/4] pip bereits vorhanden.
)

:: --- Install dependencies ---
echo [3/4] Installiere Abhaengigkeiten...
"%PYTHON%" -m pip install --no-warn-script-location -q -r requirements.txt
"%PYTHON%" -m pip install --no-warn-script-location -q waitress

echo [4/4] Fertig!
echo.
echo ══════════════════════════════════════════════════════════════
echo   Einrichtung abgeschlossen!
echo   Starten Sie das Spiel mit: start.bat
echo ══════════════════════════════════════════════════════════════
echo.
pause
