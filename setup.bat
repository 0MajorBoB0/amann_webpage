@echo off

chcp 65001 >nul

setlocal


echo ══════════════════════════════════════════════════════════════

echo   Vaccination Game - Ersteinrichtung

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

:: --- Enable site-packages in embedded Python ---

echo [1/4] Aktiviere site-packages...

 

:: Finde die richtige .pth Datei (python312._pth oder python311._pth etc.)

for %%f in (python\python*._pth) do (

    set PTH_FILE=%%f

)

 
if defined PTH_FILE (

    findstr /C:"import site" "%PTH_FILE%" >nul 2>&1

    if errorlevel 1 (

        echo import site>> "%PTH_FILE%"

        echo       site-packages aktiviert in %PTH_FILE%

    ) else (

        echo       bereits aktiviert.

    )

) else (

    echo       [WARNUNG] Keine ._pth Datei gefunden!

)

:: --- Check if pip works ---

echo [2/4] Pruefe pip...

"%PYTHON%" -m pip --version >nul 2>&1

if errorlevel 1 (

    echo       pip nicht gefunden, installiere...

    :: Download get-pip.py

    if not exist "get-pip.py" (

        echo       Lade get-pip.py herunter...

        powershell -Command "Invoke-WebRequest -Uri 'https://bootstrap.pypa.io/get-pip.py' -OutFile 'get-pip.py'"

    )

    :: Install pip

    "%PYTHON%" get-pip.py --no-warn-script-location

    :: Cleanup

    del get-pip.py 2>nul

    :: Verify

    "%PYTHON%" -m pip --version >nul 2>&1

    if errorlevel 1 (

        echo [FEHLER] pip Installation fehlgeschlagen!

        pause

        exit /b 1

    )

    echo       pip erfolgreich installiert.

) else (

    echo       pip ist bereit.

)

:: --- Install dependencies ---

echo [3/4] Installiere Abhaengigkeiten...

"%PYTHON%" -m pip install --no-warn-script-location -q --upgrade pip

"%PYTHON%" -m pip install --no-warn-script-location -q -r requirements.txt

if errorlevel 1 (

    echo [FEHLER] Abhaengigkeiten konnten nicht installiert werden!

    pause

    exit /b 1

)

"%PYTHON%" -m pip install --no-warn-script-location -q waitress

echo [4/4] Fertig!

echo.

echo ══════════════════════════════════════════════════════════════

echo   Einrichtung abgeschlossen!

echo   Starten Sie das Spiel mit: start.bat

echo ══════════════════════════════════════════════════════════════

echo.

pause