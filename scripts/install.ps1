# Project Radar - one-command installer (Python edition)
# Usage (paste into PowerShell and press Enter):
#   irm https://raw.githubusercontent.com/123456342g-lang/project-radar/main/scripts/install.ps1 | iex
$ErrorActionPreference = 'Stop'
$dest = Join-Path $env:LOCALAPPDATA 'project-radar'
$zipUrl = 'https://codeload.github.com/123456342g-lang/project-radar/zip/refs/heads/main'
$gui = 'http://127.0.0.1:8020'

function Test-Gui {
    try { $null = Invoke-WebRequest "$gui/api/health" -TimeoutSec 2 -UseBasicParsing; $true } catch { $false }
}

# Already running -> just open the GUI
if (Test-Gui) { Start-Process $gui; return }

# Prerequisite: Python
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Host 'Python not found. Opening the download page - install it' -ForegroundColor Yellow
    Write-Host '(be sure to check "Add Python to PATH"), then run this command again.'
    Write-Host '  https://www.python.org/downloads/'
    Start-Process 'https://www.python.org/downloads/'
    Read-Host 'Press Enter to close'
    return
}
python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)"
if ($LASTEXITCODE -ne 0) {
    Write-Host 'Python 3.10+ is required. Opening the download page:' -ForegroundColor Yellow
    Start-Process 'https://www.python.org/downloads/'
    Read-Host 'Press Enter to close'
    return
}

Write-Host '[1/3] Downloading Project Radar ...'
$tmpZip = Join-Path $env:TEMP 'project-radar.zip'
Invoke-WebRequest $zipUrl -OutFile $tmpZip
$tmpDir = Join-Path $env:TEMP ('pr-' + [guid]::NewGuid().ToString('N').Substring(0, 8))
Expand-Archive $tmpZip -DestinationPath $tmpDir -Force
$src = (Get-ChildItem $tmpDir -Directory | Select-Object -First 1).FullName
New-Item -ItemType Directory -Force -Path $dest | Out-Null
Copy-Item "$src\*" -Destination $dest -Recurse -Force

Write-Host '[2/3] Installing dependencies (first run takes about a minute) ...'
Push-Location $dest
try {
    if (-not (Test-Path '.venv')) { python -m venv .venv }
    & '.venv\Scripts\python.exe' -m pip install --quiet --disable-pip-version-check -r requirements.txt
    if ($LASTEXITCODE -ne 0) { Write-Host 'Dependency install failed - check your network and retry.' -ForegroundColor Red; return }
    if (-not (Test-Path '.env')) { Copy-Item '.env.example' '.env' }
} finally { Pop-Location }

Write-Host '[3/3] Starting the server ...'
Start-Process -FilePath (Join-Path $dest '.venv\Scripts\python.exe') `
    -ArgumentList '-m', 'uvicorn', 'backend.app.main:app', '--host', '127.0.0.1', '--port', '8020', '--log-level', 'warning' `
    -WorkingDirectory $dest -WindowStyle Hidden
foreach ($i in 1..30) { Start-Sleep -Seconds 2; if (Test-Gui) { break } }

if (Test-Gui) {
    Start-Process $gui
    Write-Host "Done! Your browser opened $gui" -ForegroundColor Green
    Write-Host 'Run this same command any time to reopen the interface.'
} else {
    Write-Host 'Startup failed - port 8020 may be in use. Close the other app and retry.' -ForegroundColor Red
}
