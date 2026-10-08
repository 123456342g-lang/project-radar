# Project Radar · 一键安装（Python 版）
# 用法（PowerShell 中粘贴回车）：
#   irm https://raw.githubusercontent.com/123456342g-lang/project-radar/main/scripts/install.ps1 | iex
$ErrorActionPreference = 'Stop'
$dest = Join-Path $env:LOCALAPPDATA 'project-radar'
$zipUrl = 'https://codeload.github.com/123456342g-lang/project-radar/zip/refs/heads/main'
$gui = 'http://127.0.0.1:8020'

function Test-Gui {
    try { $null = Invoke-WebRequest "$gui/api/health" -TimeoutSec 2 -UseBasicParsing; $true } catch { $false }
}

# 已在运行 → 直接打开界面
if (Test-Gui) { Start-Process $gui; return }

# 前置检查：Python
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Host '未检测到 Python。正在打开下载页，请安装（务必勾选 Add Python to PATH）：' -ForegroundColor Yellow
    Write-Host '  https://www.python.org/downloads/'
    Start-Process 'https://www.python.org/downloads/'
    Read-Host '安装完成后重新运行本命令，按回车退出'
    return
}
python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)"
if ($LASTEXITCODE -ne 0) {
    Write-Host 'Python 版本过低（需要 3.10+）。正在打开下载页：' -ForegroundColor Yellow
    Start-Process 'https://www.python.org/downloads/'
    Read-Host '安装完成后重新运行本命令，按回车退出'
    return
}

Write-Host '[1/3] 下载 Project Radar ...'
$tmpZip = Join-Path $env:TEMP 'project-radar.zip'
Invoke-WebRequest $zipUrl -OutFile $tmpZip
$tmpDir = Join-Path $env:TEMP ('pr-' + [guid]::NewGuid().ToString('N').Substring(0, 8))
Expand-Archive $tmpZip -DestinationPath $tmpDir -Force
$src = (Get-ChildItem $tmpDir -Directory | Select-Object -First 1).FullName
New-Item -ItemType Directory -Force -Path $dest | Out-Null
Copy-Item "$src\*" -Destination $dest -Recurse -Force

Write-Host '[2/3] 安装运行环境（首次约 1 分钟）...'
Push-Location $dest
try {
    if (-not (Test-Path '.venv')) { python -m venv .venv }
    & '.venv\Scripts\python.exe' -m pip install --quiet --disable-pip-version-check -r requirements.txt
    if ($LASTEXITCODE -ne 0) { Write-Host '依赖安装失败，请检查网络后重试' -ForegroundColor Red; return }
    if (-not (Test-Path '.env')) { Copy-Item '.env.example' '.env' }
} finally { Pop-Location }

Write-Host '[3/3] 启动服务 ...'
Start-Process -FilePath (Join-Path $dest '.venv\Scripts\python.exe') `
    -ArgumentList '-m', 'uvicorn', 'backend.app.main:app', '--host', '127.0.0.1', '--port', '8020', '--log-level', 'warning' `
    -WorkingDirectory $dest -WindowStyle Hidden
foreach ($i in 1..30) { Start-Sleep -Seconds 2; if (Test-Gui) { break } }

if (Test-Gui) {
    Start-Process $gui
    Write-Host "完成！浏览器已打开 $gui" -ForegroundColor Green
    Write-Host '以后再次运行本命令即可直接打开界面。'
} else {
    Write-Host '启动失败：8020 端口可能被占用，请关闭占用程序后重试' -ForegroundColor Red
}
