[CmdletBinding()]
param()

$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $PSScriptRoot
$binary = Join-Path $root 'bin\sqlite-restart-recovery.exe'
$processName = [System.IO.Path]::GetFileNameWithoutExtension($binary)

foreach ($process in @(Get-Process -Name $processName -ErrorAction SilentlyContinue)) {
    Stop-Process -Id $process.Id -Force
    Write-Host "Stopped host PID $($process.Id)"
}
foreach ($process in @(Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -and $_.CommandLine -like '*synthetic_core.py*' })) {
    Stop-Process -Id $process.ProcessId -Force
    Write-Host "Stopped Core test double PID $($process.ProcessId)"
}

Write-Host 'Cleanup completed. Evidence, checkpoint, and synthetic database were preserved.'
