# Vaccination Game – One-Click Setup + Run + Cloudflared Quick Tunnel (Windows)
$ErrorActionPreference = "Stop"

# 1) Project dir = directory of this script
$PROJECT_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $PROJECT_DIR

if (!(Test-Path ".\app.py")) {
    Write-Error "app.py not found. Put run.ps1 in the same folder as app.py."
    exit 1
}

# 2) Find Python (prefer py launcher)
function Get-PythonCmd {
    if (Get-Command py -ErrorAction SilentlyContinue) { return "py" }
    if (Get-Command python -ErrorAction SilentlyContinue) { return "python" }
    return $null
}

$PY = Get-PythonCmd
if (-not $PY) {
    Write-Error "Python not found (no 'py' and no 'python'). Please install Python."
    exit 1
}

# 3) Create/repair venv
$VENV_DIR = ".\.venv"
$ACTIVATE = "$VENV_DIR\Scripts\Activate.ps1"
$VENV_PY  = "$VENV_DIR\Scripts\python.exe"

$needVenv = $false
if (!(Test-Path $ACTIVATE)) { $needVenv = $true }
elseif (!(Test-Path $VENV_PY)) { $needVenv = $true }

if ($needVenv) {
    Write-Host "Creating/repairing venv..."
    if (Test-Path $VENV_DIR) { Remove-Item -Recurse -Force $VENV_DIR }
    & $PY -m venv $VENV_DIR
}

# 4) Activate venv
& $ACTIVATE
Write-Host "venv activated"

# 5) Ensure pip + install deps
python -m pip install --upgrade pip | Out-Host

if (Test-Path ".\requirements.txt") {
    Write-Host "Installing requirements.txt..."
    python -m pip install -r .\requirements.txt | Out-Host
} else {
    Write-Host "requirements.txt not found - skipping."
}

# Ensure waitress exists even if requirements.txt is incomplete
python -m pip install waitress | Out-Host

# 6) Ensure serve_waitress.py exists (robust server start without quoting issues)
$SERVE_FILE = ".\serve_waitress.py"
if (!(Test-Path $SERVE_FILE)) {
    Write-Host "Creating serve_waitress.py..."
@"
from app import app
from waitress import serve
import os

port = int(os.environ.get("PORT", "8000"))
threads = int(os.environ.get("THREADS", "16"))

serve(app, host="127.0.0.1", port=port, threads=threads)
"@ | Set-Content -Encoding UTF8 $SERVE_FILE
}

# 7) Secrets (local & persistent, DO NOT COMMIT)
$SECRETS_FILE = ".\.secrets.ps1"

if (!(Test-Path $SECRETS_FILE)) {
    Write-Host "Creating .secrets.ps1 (local secrets; do not commit)..."
    $secretKey = python -c "import secrets; print(secrets.token_urlsafe(48))"
    $adminPw   = python -c "import secrets; print(secrets.token_urlsafe(18))"

@"
# Local secrets - DO NOT COMMIT!
`$env:FLASK_ENV="production"
`$env:SECRET_KEY="$secretKey"
`$env:ADMIN_PASSWORD="$adminPw"
"@ | Set-Content -Encoding UTF8 $SECRETS_FILE

    Write-Host ""
    Write-Host "ADMIN PASSWORD (save it now):"
    Write-Host $adminPw
    Write-Host ""
    Write-Host "You can change it later by editing .secrets.ps1"
    Write-Host ""
}

# Load secrets into environment
. $SECRETS_FILE

# 8) Start server (Waitress)
$PORT = 8000
$THREADS = 16
$env:PORT = "$PORT"
$env:THREADS = "$THREADS"

Write-Host "Starting local server on http://127.0.0.1:$PORT/"
$serverProc = Start-Process -PassThru -NoNewWindow python -ArgumentList @(".\serve_waitress.py")

Start-Sleep -Seconds 1

# 9) Ensure cloudflared.exe (download if missing)
$CLOUDFLARED = Join-Path $PROJECT_DIR "cloudflared.exe"
if (!(Test-Path $CLOUDFLARED)) {
    Write-Host "Downloading cloudflared.exe..."
    $url = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"
    Invoke-WebRequest -Uri $url -OutFile $CLOUDFLARED
}

# 10) Start Quick Tunnel and extract URL from logs
Write-Host "Starting Cloudflare Quick Tunnel..."

$stdoutLog = Join-Path $PROJECT_DIR "cloudflared.out.log"
$stderrLog = Join-Path $PROJECT_DIR "cloudflared.err.log"

# Kill any old cloudflared still running (prevents locked log files)
Get-Process cloudflared -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Milliseconds 300

# If logs exist, rename them instead of deleting (avoids lock issues)
if (Test-Path $stdoutLog) {
    $bak = $stdoutLog + ".bak"
    try { Remove-Item $bak -Force -ErrorAction SilentlyContinue } catch {}
    try { Rename-Item $stdoutLog $bak -Force } catch {}
}
if (Test-Path $stderrLog) {
    $bak2 = $stderrLog + ".bak"
    try { Remove-Item $bak2 -Force -ErrorAction SilentlyContinue } catch {}
    try { Rename-Item $stderrLog $bak2 -Force } catch {}
}

# IMPORTANT: use http2 instead of quic (often more stable in restricted networks)
$tunnelArgs = @("tunnel","--url","http://127.0.0.1:$PORT","--protocol","http2","--no-autoupdate")
$tunnelProc = Start-Process -PassThru -NoNewWindow $CLOUDFLARED -ArgumentList $tunnelArgs `
    -RedirectStandardOutput $stdoutLog -RedirectStandardError $stderrLog

$publicUrl = $null
for ($i=0; $i -lt 90; $i++) {
    Start-Sleep -Seconds 1

    $txt = ""
    if (Test-Path $stdoutLog) { $txt = (Get-Content $stdoutLog -Raw) }
    if (-not $txt) { $txt = "" }

    $txt2 = ""
    if (Test-Path $stderrLog) { $txt2 = (Get-Content $stderrLog -Raw) }
    if (-not $txt2) { $txt2 = "" }

    $m = [regex]::Match($txt + "`n" + $txt2, "https://[a-z0-9-]+\.trycloudflare\.com")
    if ($m.Success) { $publicUrl = $m.Value; break }
}

Write-Host ""
if ($publicUrl) {
    Write-Host "PUBLIC LINK:"
    Write-Host $publicUrl
} else {
    Write-Host "Could not auto-detect the public link."
    Write-Host "Check cloudflared.out.log / cloudflared.err.log for a trycloudflare URL."
}

Write-Host ""
Write-Host "Admin local:  http://127.0.0.1:$PORT/admin"
Write-Host "Health local: http://127.0.0.1:$PORT/healthz"
Write-Host ""

# 11) Controlled stop: only stop when user types 'close server'
Write-Host "Server is running."
Write-Host "Type 'close server' and press ENTER to stop."
Write-Host ""

while ($true) {
    $cmd = Read-Host ">"
    if ($cmd -eq "close server") {
        Write-Host "Stopping server and tunnel..."
        break
    } else {
        Write-Host "Unknown command. To stop, type: close server"
    }
}

# Cleanup
try {
    if ($tunnelProc -and !$tunnelProc.HasExited) {
        $tunnelProc.Kill()
    }
} catch {}

try {
    if ($serverProc -and !$serverProc.HasExited) {
        $serverProc.Kill()
    }
} catch {}

Write-Host "Stopped."
