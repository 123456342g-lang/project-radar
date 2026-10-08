# Project Radar - one-command installer (Docker edition)
# Usage (paste into PowerShell and press Enter):
#   irm https://raw.githubusercontent.com/123456342g-lang/project-radar/main/scripts/install-docker.ps1 | iex
$ErrorActionPreference = 'Stop'
$dest = Join-Path $env:LOCALAPPDATA 'project-radar'
$zipUrl = 'https://codeload.github.com/123456342g-lang/project-radar/zip/refs/heads/main'
$gui = 'http://127.0.0.1:8020'

function Test-Gui {
    try { $null = Invoke-WebRequest "$gui/api/health" -TimeoutSec 2 -UseBasicParsing; $true } catch { $false }
}

# Already running -> just open the GUI
if (Test-Gui) { Start-Process $gui; return }

# Prerequisite: Docker Desktop
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Host 'Docker Desktop not found. Opening the download page -' -ForegroundColor Yellow
    Write-Host 'install and start it, then run this command again.'
    Write-Host '  https://www.docker.com/products/docker-desktop/'
    Start-Process 'https://www.docker.com/products/docker-desktop/'
    Read-Host 'Press Enter to close'
    return
}

# Start the engine if it is not running yet
docker info 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host '[0/3] Starting Docker Desktop ...'
    $dd = 'C:\Program Files\Docker\Docker\Docker Desktop.exe'
    if (Test-Path $dd) { Start-Process $dd }
    foreach ($i in 1..45) {
        Start-Sleep -Seconds 4
        docker info 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) { break }
    }
    if ($LASTEXITCODE -ne 0) {
        Write-Host 'Could not start the Docker engine. Open Docker Desktop manually and retry.' -ForegroundColor Red
        return
    }
}

Write-Host '[1/3] Downloading Project Radar ...'
$tmpZip = Join-Path $env:TEMP 'project-radar.zip'
Invoke-WebRequest $zipUrl -OutFile $tmpZip
$tmpDir = Join-Path $env:TEMP ('pr-' + [guid]::NewGuid().ToString('N').Substring(0, 8))
Expand-Archive $tmpZip -DestinationPath $tmpDir -Force
$src = (Get-ChildItem $tmpDir -Directory | Select-Object -First 1).FullName
New-Item -ItemType Directory -Force -Path $dest | Out-Null
Copy-Item "$src\*" -Destination $dest -Recurse -Force

Push-Location $dest
try {
    if (-not (Test-Path '.env')) { Copy-Item '.env.example' '.env' }

    Write-Host '[2/3] Building and starting the container (first run takes a few minutes) ...'
    docker compose up --build -d
    if ($LASTEXITCODE -ne 0) {
        Write-Host 'Docker failed to start. Check logs with:' -ForegroundColor Red
        Write-Host "  cd $dest; docker compose logs"
        return
    }
} finally { Pop-Location }

Write-Host '[3/3] Waiting for the interface ...'
foreach ($i in 1..60) { Start-Sleep -Seconds 2; if (Test-Gui) { break } }

if (Test-Gui) {
    Start-Process $gui
    Write-Host "Done! Your browser opened $gui" -ForegroundColor Green
    Write-Host 'Run this same command any time to reopen the interface.'
    Write-Host 'Tip: paste your Jev key in the GUI "Settings - API keys" panel to enable the Jev judge.'
} else {
    Write-Host 'Startup timed out - port 8020 may be in use.' -ForegroundColor Red
}
