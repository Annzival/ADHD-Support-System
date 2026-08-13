[CmdletBinding()]
param(
    [switch]$RemoveFixedRuntime
)

$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $PSScriptRoot
$binary = Join-Path $root 'bin\wails-v3-windows-thin-host.exe'
$coreScript = Join-Path $root 'agent_core\agent_core_stub.py'
$runValueName = 'ADHDSupportSystemV01Spike'

$hosts = @(Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -eq $binary })
foreach ($process in $hosts) {
    Stop-Process -Id $process.ProcessId -Force
    Write-Host "已停止验证宿主 PID $($process.ProcessId)"
}
$cores = @(Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like "*$coreScript*" })
foreach ($process in $cores) {
    Stop-Process -Id $process.ProcessId -Force
    Write-Host "已停止测试替身 PID $($process.ProcessId)"
}

Remove-ItemProperty -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run' -Name $runValueName -ErrorAction SilentlyContinue
Write-Host '已移除本 spike 的开机启动注册项（如存在）。'

if ($RemoveFixedRuntime) {
    $versions = Get-Content (Join-Path $root 'versions.json') -Raw | ConvertFrom-Json
    $runtimeRoot = Join-Path $root ".tools\webview2-fixed-$($versions.candidates.webview2.version)-$($versions.candidates.webview2.architecture)"
    if (Test-Path $runtimeRoot) {
        Remove-Item -LiteralPath $runtimeRoot -Recurse -Force
        Write-Host "已删除本地 Fixed Version Runtime：$runtimeRoot"
    }
}
Write-Host '清理完成。证据目录保持不变，便于回传。'
