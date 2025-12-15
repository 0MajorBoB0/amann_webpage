# Vaccination Game – One-Click Setup + Run + Cloudflared Quick Tunnel (Windows)
$ErrorActionPreference = "Stop"

# --- Project root ---
$PROJECT_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $PROJECT_DIR

if (!(Test-Path ".\app.py")) {
    Write-Error "app.py not found. Put run.ps1 in the same folder as app.py."
    exit 1
}

# --- Python discovery ---
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

# --- venv bootstrap ---
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

& $ACTIVATE
Write-Host "venv activated"

# --- deps ---
python -m pip install --upgrade pip | Out-Host
if (Test-Path ".\requirements.txt") {
    Write-Host "Installing requirements.txt..."
    python -m pip install -r .\requirements.txt | Out-Host
} else {
    Write-Host "requirements.txt not found - skipping."
}
python -m pip install waitress | Out-Host

# --- server entrypoint helper ---
$SERVE_FILE = ".\serve_waitress.py"
if (!(Test-Path $SERVE_FILE)) {
    Write-Host "Creating serve_waitress.py..."
    $serveLines = @(
        'from app import app, init_db',
        'from waitress import serve',
        'import os',
        '',
        'init_db()',
        'port = int(os.environ.get("PORT", "8000"))',
        'threads = int(os.environ.get("THREADS", "16"))',
        'serve(app, host="127.0.0.1", port=port, threads=threads)',
        ''
    )
    $serveLines | Set-Content -Encoding UTF8 $SERVE_FILE
}

# --- DB backup helper (consistent snapshot) ---
$BACKUP_PY = ".\backup_db.py"
if (!(Test-Path $BACKUP_PY)) {
    Write-Host "Creating backup_db.py..."
    $backupLines = @(
        'import os, sqlite3, datetime, sys',
        '',
        'root = os.path.dirname(os.path.abspath(__file__))',
        'src  = os.path.join(root, "game.db")',
        'dst_dir = os.path.join(root, "backups")',
        'os.makedirs(dst_dir, exist_ok=True)',
        '',
        'if not os.path.exists(src):',
        '    print("NO_DB")',
        '    sys.exit(0)',
        '',
        'ts = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")',
        'dst = os.path.join(dst_dir, f"game_{ts}.db")',
        '',
        'con = sqlite3.connect(src)',
        'try:',
        '    con.execute("PRAGMA wal_checkpoint(FULL);")',
        'except Exception:',
        '    pass',
        '',
        'bck = sqlite3.connect(dst)',
        'con.backup(bck)',
        'bck.close()',
        'con.close()',
        '',
        'print(dst)',
        ''
    )
    $backupLines | Set-Content -Encoding UTF8 $BACKUP_PY
}

# --- fresh secrets each run ---
$secretKey = python -c "import secrets; print(secrets.token_urlsafe(48))"
$adminPw   = python -c "import secrets; print(secrets.token_urlsafe(18))"

$env:FLASK_ENV   = "production"
$env:FLASK_DEBUG = "0"
$env:SECRET_KEY  = "$secretKey"
$env:ADMIN_PASSWORD = "$adminPw"

Write-Host ""
Write-Host "ADMIN PASSWORD (new for this server run):"
Write-Host $adminPw
Write-Host ""

# --- start server ---
$PORT = 8000
$THREADS = 48
$env:PORT = "$PORT"
$env:THREADS = "$THREADS"

Write-Host "Starting local server on http://127.0.0.1:$PORT/"
$serverProc = Start-Process -PassThru -NoNewWindow python -ArgumentList @(".\serve_waitress.py")

# --- wait for /healthz ---
$healthUrl = "http://127.0.0.1:$PORT/healthz"
Write-Host "Waiting for server health check: $healthUrl"

$healthy = $false
for ($i=0; $i -lt 60; $i++) {
    try {
        $resp = Invoke-WebRequest -Uri $healthUrl -UseBasicParsing -TimeoutSec 2
        if ($resp.StatusCode -eq 200) { $healthy = $true; break }
    } catch { Start-Sleep -Seconds 1 }
}

if (-not $healthy) {
    Write-Error "Server did not become healthy within 60s. Check logs."
    try { if ($serverProc -and !$serverProc.HasExited) { $serverProc.Kill() } } catch {}
    exit 1
}
Write-Host "Server is healthy."

# --- cloudflared setup ---
$CLOUDFLARED = Join-Path $PROJECT_DIR "cloudflared.exe"
if (!(Test-Path $CLOUDFLARED)) {
    Write-Host "Downloading cloudflared.exe..."
    $url = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"
    Invoke-WebRequest -Uri $url -OutFile $CLOUDFLARED
}

Write-Host "Starting Cloudflare Quick Tunnel..."

$stdoutLog = Join-Path $PROJECT_DIR "cloudflared.out.log"
$stderrLog = Join-Path $PROJECT_DIR "cloudflared.err.log"

Get-Process cloudflared -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Milliseconds 300

# --- rotate logs ---
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

# --- start tunnel (http2 is usually more stable) ---
$tunnelArgs = @("tunnel","--url","http://127.0.0.1:$PORT","--protocol","http2","--no-autoupdate")
$tunnelProc = Start-Process -PassThru -NoNewWindow $CLOUDFLARED -ArgumentList $tunnelArgs `
    -RedirectStandardOutput $stdoutLog -RedirectStandardError $stderrLog

# --- detect public URL ---
$publicUrl = $null
for ($i=0; $i -lt 90; $i++) {
    Start-Sleep -Seconds 1
    $txt  = if (Test-Path $stdoutLog) { (Get-Content $stdoutLog -Raw) } else { "" }
    $txt2 = if (Test-Path $stderrLog) { (Get-Content $stderrLog -Raw) } else { "" }
    $m = [regex]::Match(($txt + "`n" + $txt2), "https://[a-z0-9-]+\.trycloudflare\.com")
    if ($m.Success) { $publicUrl = $m.Value; break }
}

Write-Host ""
if ($publicUrl) {
    Write-Host "PUBLIC LINK (share with students):"
    Write-Host $publicUrl
    Write-Host ""
    Write-Host "Admin PUBLIC:"
    Write-Host ($publicUrl.TrimEnd("/") + "/admin")
} else {
    Write-Host "Could not auto-detect the public link."
    Write-Host "Check cloudflared.out.log / cloudflared.err.log for a trycloudflare URL."
}

Write-Host ""
Write-Host "Admin LOCAL:  http://127.0.0.1:$PORT/admin"
Write-Host "Health LOCAL: $healthUrl"
Write-Host ""

# --- controlled stop ---
Write-Host "Server is running."
Write-Host "Type 'close server' and press ENTER to stop."
Write-Host ""

try {
    while ($true) {
        $cmd = Read-Host ">"
        if ($cmd -eq "close server") {
            Write-Host "Stopping server and tunnel..."
            break
        } else {
            Write-Host "Unknown command. To stop, type: close server"
        }
    }
}
finally {
    # --- cleanup ---
    try { if ($tunnelProc -and !$tunnelProc.HasExited) { $tunnelProc.Kill() } } catch {}
    try { if ($serverProc -and !$serverProc.HasExited) { $serverProc.Kill() } } catch {}

    Start-Sleep -Milliseconds 400

    # --- DB backup on shutdown ---
    try {
        $out = (python .\backup_db.py) | Out-String
        $out = $out.Trim()
        if ($out -and $out -ne "NO_DB") {
            Write-Host "DB backup created:"
            Write-Host $out
        } else {
            Write-Host "No game.db found yet - skipping backup."
        }
    } catch {
        Write-Host "Backup failed (non-fatal)."
    }

    Write-Host "Stopped."
}
