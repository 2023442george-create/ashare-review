<#
一键启动：复盘罗盘

设计目标：双击即用，且不骗人。
- 已经在跑 → 直接打开浏览器，不重复起进程
- 没在跑 → 后台拉起 uvicorn，从启动日志里读出**实际**端口，健康检查通过后再开浏览器
- 全程不弹黑窗；失败时弹消息框并告诉你去哪看日志

参数：
  -Port 18080   强制指定端口（默认交给 run.py 自动挑）
  -NoBrowser    只启动，不开浏览器（自检用）
  -Rebuild      启动前重新构建前端
#>
param(
  [int]$Port = 0,
  [switch]$NoBrowser,
  [switch]$Rebuild
)

$ErrorActionPreference = 'Stop'

$root    = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root 'backend'
$logs    = Join-Path $root 'logs'
$logFile = Join-Path $logs 'app.log'
$errFile = Join-Path $logs 'app.err.log'
$portFile = Join-Path $logs 'app.port'
$pidFile  = Join-Path $logs 'app.pid'

New-Item -ItemType Directory -Path $logs -Force | Out-Null

function Show-Fail([string]$msg) {
  try {
    Add-Type -AssemblyName System.Windows.Forms
    [void][System.Windows.Forms.MessageBox]::Show($msg, '复盘罗盘 · 启动失败', 'OK', 'Error')
  } catch {
    Write-Host $msg -ForegroundColor Red
  }
}

# 本机 127.0.0.1 不能走系统代理（这台机器上挂着 127.0.0.1:4653，会把 localhost 也拦下来）。
# 用 WebRequest 并显式 Proxy=$null：System.Net.Http 在 PS 5.1 里默认没加载，
# New-Object HttpClient 会直接报“找不到类型”，导致健康检查永远为 false。
function Test-App([int]$p) {
  if ($p -le 0) { return $false }
  try {
    $req = [System.Net.WebRequest]::Create("http://127.0.0.1:$p/api/health")
    $req.Proxy = $null
    $req.Timeout = 2000
    $req.ReadWriteTimeout = 2000
    $resp = $req.GetResponse()
    $code = [int]$resp.StatusCode
    $resp.Close()
    return ($code -eq 200)
  } catch { return $false }
}

function Open-App([int]$p) {
  if ($NoBrowser) { Write-Host "[i] -NoBrowser：未打开浏览器，地址 http://127.0.0.1:$p" ; return }
  Start-Process "http://127.0.0.1:$p" | Out-Null
}

# ---------- 1. 已经在跑就直接开 ----------
$running = 0
if (Test-Path $portFile) {
  $raw = (Get-Content $portFile -Raw -ErrorAction SilentlyContinue)
  if ($raw) { [void][int]::TryParse($raw.Trim(), [ref]$running) }
}
if ($Port -gt 0 -and (Test-App $Port)) { $running = $Port }

if (Test-App $running) {
  Write-Host "[i] 已在运行：http://127.0.0.1:$running"
  Open-App $running
  exit 0
}

# 端口文件丢了但实例还在：扫一遍候选端口，避免起第二个
if ($running -eq 0) {
  foreach ($c in 18080, 18081, 18888, 19090, 28080, 9090, 8088, 8080) {
    if (Test-App $c) {
      $c | Set-Content $portFile -Encoding ascii
      Write-Host "[i] 发现已在运行的实例：http://127.0.0.1:$c"
      Open-App $c
      exit 0
    }
  }
}

# ---------- 2. 选解释器 ----------
$py = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $py)) { $py = 'python' }

# ---------- 3. 前端产物 ----------
$indexHtml = Join-Path $backend 'static\index.html'
$needBuild = $Rebuild -or (-not (Test-Path $indexHtml))
if ($needBuild) {
  $npm = Get-Command npm -ErrorAction SilentlyContinue
  if ($npm) {
    Write-Host '[i] 构建前端...'
    Push-Location (Join-Path $root 'frontend')
    try { & npm run build 2>&1 | Out-Null } catch { Write-Host "[!] 前端构建失败，继续启动（界面可能是旧版本）" }
    Pop-Location
  } else {
    Write-Host '[!] 未找到 npm，跳过前端构建'
  }
  if (-not (Test-Path $indexHtml)) {
    Write-Host '[!] 仍无前端产物，页面会 404，但 API 可用'
  }
}

# ---------- 4. 启动后端 ----------
# 不能用 Start-Process：这台机器的环境里同时存在 HTTPS_PROXY 和 https_proxy，
# PS 5.1 的 Start-Process 重建环境变量字典时会抛 “已添加项” 而启动失败。
# 改用 .NET 直接起进程（原样继承环境块），输出由 run.py 自己按 REVIEW_LOG 写文件。
if ($Port -gt 0) { $env:REVIEW_PORT = $Port }
Remove-Item $logFile, $errFile -Force -ErrorAction SilentlyContinue
$env:REVIEW_LOG = $logFile

$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = $py
$psi.Arguments = 'run.py'
$psi.WorkingDirectory = $backend
$psi.UseShellExecute = $false
$psi.CreateNoWindow = $true

$proc = [System.Diagnostics.Process]::Start($psi)
if (-not $proc) {
  Show-Fail "无法启动进程：$py`n`n请检查 .venv\Scripts\python.exe 是否存在。"
  exit 1
}
$proc.Id | Set-Content $pidFile -Encoding ascii
Write-Host "[i] 进程已拉起（pid $($proc.Id)），等待服务就绪…首次启动要预热缓存，约 10-20 秒"

# ---------- 5. 从日志读实际端口（run.py 会自动挑端口） ----------
$url = $null
for ($i = 0; $i -lt 60; $i++) {
  Start-Sleep -Milliseconds 400
  if (Test-Path $logFile) {
    $m = Select-String -Path $logFile -Pattern 'http://127\.0\.0\.1:(\d+)' -ErrorAction SilentlyContinue |
         Select-Object -First 1
    if ($m) { $url = $m.Matches[0].Value; break }
  }
  try { if ($proc.HasExited) { break } } catch {}
}

if (-not $url) {
  $tail = ''
  if (Test-Path $logFile) { $tail = (Get-Content $logFile -Tail 12 -ErrorAction SilentlyContinue) -join "`n" }
  Show-Fail "后端没有起来，没能绑定到任何端口。`n`n日志：$logFile`n`n$tail"
  exit 1
}

$realPort = [int]($url.Split(':')[-1])
$realPort | Set-Content $portFile -Encoding ascii

# ---------- 6. 等健康检查 ----------
$ok = $false
for ($i = 0; $i -lt 180; $i++) {
  if (Test-App $realPort) { $ok = $true; break }
  Start-Sleep -Milliseconds 500
  try { if ($proc.HasExited) { break } } catch {}
}

if (-not $ok) {
  Show-Fail "服务进程在跑，但 http://127.0.0.1:$realPort/api/health 一直不通。`n`n日志：$logFile"
  exit 1
}

Write-Host "[ok] 已启动：http://127.0.0.1:$realPort"
Open-App $realPort
exit 0
