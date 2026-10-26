<#
创建桌面快捷方式（带图标）。

为什么需要你手动跑一次：创建 .lnk 必须调用 WScript.Shell 这个 COM 组件，
而 Agent 侧的 PowerShell 被安全策略禁止实例化 COM 对象。这个脚本只做一件事，
就是替你调一次 COM，内容可自行审阅。

用法：右键本文件 → 使用 PowerShell 运行
     或：powershell -NoProfile -ExecutionPolicy Bypass -File scripts\install_shortcut.ps1
#>
$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
$desktop = [Environment]::GetFolderPath('Desktop')
$lnkPath = Join-Path $desktop '复盘罗盘.lnk'

$ws = New-Object -ComObject WScript.Shell
$sc = $ws.CreateShortcut($lnkPath)
$sc.TargetPath = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$sc.Arguments = '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + (Join-Path $root 'scripts\launch.ps1') + '"'
$sc.WorkingDirectory = $root
$icon = Join-Path $root 'assets\app.ico'
if (Test-Path $icon) { $sc.IconLocation = "$icon,0" }
$sc.Description = '一键启动 A股复盘罗盘：后台起服务并打开浏览器'
$sc.Save()

if (Test-Path $lnkPath) {
  Write-Host "[ok] 已创建：$lnkPath" -ForegroundColor Green
} else {
  Write-Host "[!] 创建失败：$lnkPath" -ForegroundColor Red
}
