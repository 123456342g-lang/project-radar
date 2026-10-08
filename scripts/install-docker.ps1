# Project Radar · 一键安装（Docker 版）
# 用法（PowerShell 中粘贴回车）：
#   irm https://raw.githubusercontent.com/123456342g-lang/project-radar/main/scripts/install-docker.ps1 | iex
$ErrorActionPreference = 'Stop'
$dest = Join-Path $env:LOCALAPPDATA 'project-radar'
$zipUrl = 'https://codeload.github.com/123456342g-lang/project-radar/zip/refs/heads/main'
$gui = 'http://127.0.0.1:8020'

function Test-Gui {
    try { $null = Invoke-WebRequest "$gui/api/health" -TimeoutSec 2 -UseBasicParsing; $true } catch { $false }
}

# 已在运行 → 直接打开界面
if (Test-Gui) { Start-Process $gui; return }

# 前置检查：Docker Desktop
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Host '未检测到 Docker Desktop。正在打开下载页，请安装并启动它：' -ForegroundColor Yellow
    Write-Host '  https://www.docker.com/products/docker-desktop/'
    Start-Process 'https://www.docker.com/products/docker-desktop/'
    Read-Host '安装完成后重新运行本命令，按回车退出'
    return
}

# 引擎未启动则自动拉起
docker info 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host '[0/3] 正在启动 Docker Desktop ...'
    $dd = 'C:\Program Files\Docker\Docker\Docker Desktop.exe'
    if (Test-Path $dd) { Start-Process $dd }
    foreach ($i in 1..45) {
        Start-Sleep -Seconds 4
        docker info 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) { break }
    }
    if ($LASTEXITCODE -ne 0) {
        Write-Host 'Docker 引擎启动失败，请手动打开 Docker Desktop 后重试' -ForegroundColor Red
        return
    }
}

Write-Host '[1/3] 下载 Project Radar ...'
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

    Write-Host '[2/3] 构建并启动容器（首次约需几分钟）...'
    docker compose up --build -d
    if ($LASTEXITCODE -ne 0) {
        Write-Host 'Docker 启动失败，可用以下命令查看日志：' -ForegroundColor Red
        Write-Host "  cd $dest; docker compose logs"
        return
    }
} finally { Pop-Location }

Write-Host '[3/3] 等待界面就绪 ...'
foreach ($i in 1..60) { Start-Sleep -Seconds 2; if (Test-Gui) { break } }

if (Test-Gui) {
    Start-Process $gui
    Write-Host "完成！浏览器已打开 $gui" -ForegroundColor Green
    Write-Host '以后再次运行本命令即可直接打开界面。'
} else {
    Write-Host '界面启动超时，请检查 8020 端口是否被占用' -ForegroundColor Red
}
