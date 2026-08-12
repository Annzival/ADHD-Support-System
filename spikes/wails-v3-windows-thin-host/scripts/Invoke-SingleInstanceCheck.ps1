[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$binary = Join-Path $root 'bin\wails-v3-windows-thin-host.exe'
$configPath = Join-Path $root '.spike-run.json'
if (-not (Test-Path $configPath)) { throw '未找到运行配置；先运行 .\scripts\Start-Spike.ps1' }
$config = Get-Content $configPath -Raw | ConvertFrom-Json
$runDir = $config.evidenceDirectory

try {
    $null = Invoke-RestMethod -Uri "http://127.0.0.1:$($config.corePort)/health" -TimeoutSec 2
} catch {
    throw '现有验证宿主或测试替身不健康；不要运行第二实例检查。'
}

$second = Start-Process -FilePath $binary -WorkingDirectory $root -PassThru -Wait
$hosts = Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -eq $binary }
$report = [ordered]@{
    generatedAt = (Get-Date).ToUniversalTime().ToString('o')
    secondInstanceExitCode = $second.ExitCode
    matchingHostPids = @($hosts.ProcessId)
    passed = ($second.ExitCode -eq 0 -and $hosts.Count -eq 1)
}
$path = Join-Path $runDir 'single-instance-check.json'
$report | ConvertTo-Json -Depth 4 | Set-Content -Path $path -Encoding UTF8
if (-not $report.passed) {
    throw "单实例检查失败：exit=$($second.ExitCode)，匹配的宿主进程数=$($hosts.Count)。"
}
Write-Host "单实例检查通过，证据：$path"
