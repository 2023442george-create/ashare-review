# 复盘罗盘 · 一键启动（Windows PowerShell）
# 用法： .\scripts\start.ps1              正常启动
#       .\scripts\start.ps1 -Offline     离线样例模式（不联网）
#       .\scripts\start.ps1 -Rebuild     强制重新构建前端
#       .\scripts\start.ps1 -NoBuild     跳过前端构建，直接起服务
#       .\scripts\start.ps1 -Port 9000   指定端口
#
# Two rules this script must never break:
#   1. The server starts even when the frontend build fails. A broken UI build is
#      annoying; a script that dies before starting the backend looks like total
#      data loss and sends you hunting in the wrong place.
#   2. The port is never changed behind your back: -Port wins, then an existing
#      $env:REVIEW_PORT, then 18080. 18080 sits outside the Windows dynamic port
#      range (1024-15000), which Hyper-V keeps reserving in random blocks — 8000
#      and 8088 have both been swallowed by those reservations. If 18080 is also
#      taken, run.py walks its candidate list and prints the real URL it bound.
param([switch]$Offline, [switch]$Rebuild, [switch]$NoBuild, [int]$Port = 0)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Test-PyExe($exe) {
  if (-not $exe -or -not (Test-Path -LiteralPath $exe)) { return $null }
  try {
    $v = & $exe --version 2>&1 | Out-String
    if ($v -match "Python 3\.(\d+)") { if ([int]$Matches[1] -ge 9) { return $exe } }
  } catch {}
  return $null
}

function Find-Python {
  # 1) explicit override
  $hit = Test-PyExe $env:REVIEW_PYTHON
  if ($hit) { return $hit }
  # 2) PATH
  foreach ($c in @("python", "python3", "py")) {
    $cmd = Get-Command $c -ErrorAction SilentlyContinue
    if ($cmd) { $hit = Test-PyExe $cmd.Source; if ($hit) { return $hit } }
  }
  # 3) conda / common install locations
  $cands = @()
  foreach ($base in @($env:USERPROFILE, $env:LOCALAPPDATA + "\Programs\Python")) {
    if ($base -and (Test-Path -LiteralPath $base)) {
      $cands += Get-ChildItem -Path $base -Filter "python.exe" -Recurse -Depth 2 -ErrorAction SilentlyContinue |
                Where-Object { $_.FullName -notmatch "envs\\.+\\envs" } |
                Select-Object -ExpandProperty FullName
    }
  }
  foreach ($c in ($cands | Select-Object -Unique)) { $hit = Test-PyExe $c; if ($hit) { return $hit } }
  return $null
}

Write-Host "== FuPan LuoPan (YouZi Edition) startup check ==" -ForegroundColor Yellow

$py = Find-Python
if (-not $py) {
  Write-Host "[x] Python 3.9+ not found. Install from https://www.python.org/downloads/" -ForegroundColor Red
  exit 1
}
Write-Host "[ok] Python: $py"

$need = (& $py -c "import importlib.util as u; print(0 if all(u.find_spec(m) for m in ['fastapi','uvicorn','httpx','apscheduler']) else 1)" 2>$null | Out-String).Trim()
if ($need -eq "1") {
  Write-Host "[..] Installing backend dependencies (first run ~1 min)..." -ForegroundColor Cyan
  & $py -m pip install -r backend\requirements.txt --quiet --disable-pip-version-check
  if ($LASTEXITCODE -ne 0) {
    Write-Host "[x] pip install failed. Check network and retry." -ForegroundColor Red
    exit 1
  }
}
Write-Host "[ok] backend dependencies ready"

$static = "backend\static\index.html"
# Rebuild when the bundle is missing OR when frontend sources are newer than it.
# Checking only for existence leaves anyone who edited the sources staring at a
# stale UI: new pages appear missing and new fields render blank, with no error.
$needBuild = $Rebuild.IsPresent -or -not (Test-Path $static)
if (-not $needBuild) {
  $srcPaths = @("frontend\src", "frontend\index.html", "frontend\package.json", "frontend\vite.config.js") |
              Where-Object { Test-Path $_ }
  $newest = $null
  if ($srcPaths.Count -gt 0) {
    $newest = Get-ChildItem -Path $srcPaths -Recurse -File -ErrorAction SilentlyContinue |
              Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 1
  }
  if ($newest -and $newest.LastWriteTimeUtc -gt (Get-Item $static).LastWriteTimeUtc) {
    Write-Host "[..] frontend source newer than bundle ($($newest.Name)) -> rebuilding" -ForegroundColor Cyan
    $needBuild = $true
  }
}
if ($needBuild -and -not $NoBuild.IsPresent) {
  $npm = Get-Command npm -ErrorAction SilentlyContinue
  if (-not $npm) {
    Write-Host "[!] npm not found; keeping the existing bundle (APIs are unaffected)" -ForegroundColor DarkYellow
  } else {
    Write-Host "[..] Rebuilding frontend (1-2 min). Ctrl+C skips it; the server still starts." -ForegroundColor Cyan
    $built = $false
    Push-Location frontend
    try {
      # npm writes its warnings to stderr, and PowerShell promotes a native
      # command's stderr to a terminating error while $ErrorActionPreference is
      # "Stop" -- which killed this script BEFORE the server line, every single
      # run. Inside this block a failure is data to report, not an exception.
      $ErrorActionPreference = "Continue"
      $vite = (Test-Path "node_modules\.bin\vite.cmd") -or (Test-Path "node_modules\.bin\vite")
      if (-not $vite) {
        Write-Host "[..] installing frontend dependencies..." -ForegroundColor Cyan
        & npm install --no-audit --no-fund 2>&1 | Out-String | Write-Host
        $vite = (Test-Path "node_modules\.bin\vite.cmd") -or (Test-Path "node_modules\.bin\vite")
      }
      if ($vite) {
        & npm run build 2>&1 | Out-String | Write-Host
        $built = ($LASTEXITCODE -eq 0) -and (Test-Path "..\backend\static\index.html")
      } else {
        Write-Host "[!] vite is not installed, skipping build" -ForegroundColor DarkYellow
      }
    } catch {
      Write-Host "[!] frontend build raised: $($_.Exception.Message)" -ForegroundColor DarkYellow
    } finally {
      $ErrorActionPreference = "Stop"
      Pop-Location
    }
    if ($built) {
      Write-Host "[ok] frontend rebuilt" -ForegroundColor Green
    } else {
      Write-Host "[!] frontend NOT rebuilt - what you see is the PREVIOUS bundle." -ForegroundColor DarkYellow
      Write-Host "    New pages are missing and new fields render blank until you run:" -ForegroundColor DarkYellow
      Write-Host "      cd frontend; npm install; npm run build" -ForegroundColor DarkYellow
      Write-Host "    The backend and every API start normally regardless." -ForegroundColor DarkYellow
    }
  }
} elseif ($needBuild) {
  Write-Host "[i] -NoBuild: skipping the frontend rebuild (UI stays on the previous bundle)" -ForegroundColor Cyan
} else {
  Write-Host "[ok] frontend bundle is up to date (backend\static)"
}

# -Port > existing $env:REVIEW_PORT > 18080. Overwriting REVIEW_PORT uncondi-
# tionally (what this used to do) silently relocates the server away from the
# port you had been using, and the browser tab you still have open goes blank.
if ($Port -le 0) {
  $envPort = 0
  if ($env:REVIEW_PORT) { [void][int]::TryParse($env:REVIEW_PORT, [ref]$envPort) }
  $Port = if ($envPort -gt 0) { $envPort } else { 18080 }
}
$env:REVIEW_PORT = $Port
if ($Offline) {
  $env:REVIEW_OFFLINE = "1"
  Write-Host "[i] OFFLINE demo mode (sample data, no network)" -ForegroundColor Cyan
}
Write-Host "== Server starting: http://127.0.0.1:$Port  (API docs: /api/docs) ==" -ForegroundColor Green
& $py backend\run.py