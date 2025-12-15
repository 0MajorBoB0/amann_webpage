@echo off

chcp 65001 >nul

 

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

    goto :end

)

 

set "PYTHON=%~dp0python\python.exe"

 

:: --- Enable site-packages in embedded Python ---

echo [1/4] Aktiviere site-packages...

 

:: Finde die ._pth Datei

set "PTH_FILE="

for %%f in (python\python*._pth) do set "PTH_FILE=%%f"

 

if "%PTH_FILE%"=="" (

    echo       [FEHLER] Keine ._pth Datei gefunden!

    goto :end

)

 

echo       Gefunden: %PTH_FILE%

 

:: Schreibe die _pth Datei komplett neu (einfachste Loesung)

:: Das aktiviert site-packages korrekt

echo python312.zip> "%PTH_FILE%"

echo .>> "%PTH_FILE%"

echo import site>> "%PTH_FILE%"

echo       site-packages aktiviert.

 

:: --- Install pip ---

echo [2/4] Installiere pip...

 

if not exist "get-pip.py" (

    echo       Lade get-pip.py herunter...

    powershell -Command "Invoke-WebRequest -Uri 'https://bootstrap.pypa.io/get-pip.py' -OutFile 'get-pip.py'"

)

 

echo       Fuehre get-pip.py aus...

"%PYTHON%" get-pip.py --no-warn-script-location

 

echo       Teste pip...

"%PYTHON%" -m pip --version

if errorlevel 1 (

    echo [FEHLER] pip Installation fehlgeschlagen!

    goto :end

)

 

del get-pip.py 2>nul

echo       pip ist bereit.

 

:: --- Install dependencies ---

echo [3/4] Installiere Abhaengigkeiten...

"%PYTHON%" -m pip install --no-warn-script-location -q --upgrade pip

"%PYTHON%" -m pip install --no-warn-script-location -q -r requirements.txt

"%PYTHON%" -m pip install --no-warn-script-location -q waitress

 

:: --- Verify flask installed ---

echo [4/4] Pruefe Installation...

"%PYTHON%" -c "import flask; print('       Flask', flask.__version__)"

if errorlevel 1 (

    echo [FEHLER] Flask konnte nicht installiert werden!

    goto :end

)

 

echo.

echo ══════════════════════════════════════════════════════════════

echo   Einrichtung abgeschlossen!

echo   Starten Sie das Spiel mit: start.bat

echo ══════════════════════════════════════════════════════════════

 

:end

echo.

pause