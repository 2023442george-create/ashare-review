<#
停止后台服务：按 logs\app.pid 结束进程；pid 失效时按 logs\app.port 找监听该端口的进程。

用法：双击 scripts\stop.cmd，或 powershell -File scripts\stop.ps1
#>
$ErrorActionPreference = 'Continue'

$root = Split-Path -Parent $PSScriptRoot
$pidFile = Join-Path $root 'logs\app.pid'
$portFile = Join-Path $root 'logs\app.port'

$killed = @()

# 1) pid 文件
if (Test-Path $pidFile) {
  $raw = (Get-Content $pidFile -Raw -ErrorAction SilentlyContinue)
  $procId = 0
  if ($raw -and [int]::TryParse($raw.Trim(), [ref]$procId) -and $procId -gt 0) {
    if (Get-Process -Id $procId -ErrorAction SilentlyContinue) { $killed += $procId }
  }
}

# 2) 监听该端口的进程（pid 文件可能记录的是启动器而不是真正 bind 的进程）
if (Test-Path $portFile) {
  $port = 0
  $rawPort = (Get-Content $portFile -Raw -ErrorAction SilentlyContinue)
  if ($rawPort -and [int]::TryParse($rawPort.Trim(), [ref]$port) -and $port -gt 0) {
    Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
      ForEach-Object { $killed += $_.OwningProcess }
  }
}

# 3) 兜底：命令行里带本项目 run.py 的 python 进程（防止端口文件丢失）
Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
  Where-Object { $_.CommandLine -and $_.CommandLine -match 'ashare-review.*run\.py' } |
  ForEach-Object { $killed += [int]$_.ProcessId }

$killed = $killed | Where-Object { $_ -gt 0 } | Select-Object -Unique

foreach ($procId in $killed) {
  Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
}

Remove-Item $pidFile, $portFile -Force -ErrorAction SilentlyContinue

if ($killed.Count -gt 0) {
  Write-Host ("[ok] 已停止（pid " + ($killed -join ', ') + "）") -ForegroundColor Green
} else {
  Write-Host "[i] 没有找到正在运行的服务" -ForegroundColor Yellow
}
