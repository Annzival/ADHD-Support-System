[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$binary = Join-Path $root 'bin\wails-v3-windows-thin-host.exe'
$configPath = Join-Path $root '.spike-run.json'
if (-not (Test-Path $configPath)) { throw '未找到运行配置；先运行 .\scripts\Start-Spike.ps1' }
$config = Get-Content $configPath -Raw | ConvertFrom-Json
$runDir = $config.evidenceDirectory
$hostProcessName = [System.IO.Path]::GetFileNameWithoutExtension($binary)
$hostStderr = Join-Path $runDir 'host-stderr.log'
if ((Test-Path $hostStderr) -and ((Get-Content $hostStderr -Raw -Encoding UTF8) -match 'read \.spike-run\.json:|parse required \.spike-run\.json:')) {
    throw '当前宿主未成功加载 .spike-run.json；不得将其作为单实例证据。请保留日志、更新 checkpoint 后重新构建并启动运行 A。'
}

function Get-SpikeHostProcesses {
    return @(Get-Process -Name $hostProcessName -ErrorAction SilentlyContinue)
}

function Test-SecondInstanceEvent {
    $eventPath = Join-Path $runDir 'host-events.jsonl'
    if (-not (Test-Path $eventPath)) { return $false }
    return @(
        Get-Content -LiteralPath $eventPath -Encoding UTF8 |
            Where-Object { $_ } |
            ForEach-Object { $_ | ConvertFrom-Json } |
            Where-Object { $_.kind -eq 'second_instance_activated' }
    ).Count -gt 0
}

try {
    $null = Invoke-RestMethod -Uri "http://127.0.0.1:$($config.corePort)/health" -TimeoutSec 2
} catch {
    throw '现有验证宿主或测试替身不健康；不要运行第二实例检查。'
}

$hostsBefore = @(Get-SpikeHostProcesses)
if ($hostsBefore.Count -ne 1) {
    throw "单实例检查开始前需要恰好一个验证宿主进程；实际为 $($hostsBefore.Count)。"
}

$second = Start-Process -FilePath $binary -WorkingDirectory $root -PassThru -Wait
$deadline = (Get-Date).AddSeconds(5)
do {
    $hostsAfter = @(Get-SpikeHostProcesses)
    $activationRecorded = Test-SecondInstanceEvent
    if ($hostsAfter.Count -eq 1 -and $activationRecorded) { break }
    Start-Sleep -Milliseconds 200
} while ((Get-Date) -lt $deadline)

$report = [ordered]@{
    generatedAt = (Get-Date).ToUniversalTime().ToString('o')
    secondInstanceExitCode = $second.ExitCode
    hostProcessName = $hostProcessName
    hostPidsBefore = @($hostsBefore.Id)
    hostPidsAfter = @($hostsAfter.Id)
    secondInstanceActivationRecorded = $activationRecorded
    passed = ($second.ExitCode -eq 0 -and $hostsAfter.Count -eq 1 -and $activationRecorded)
}
$path = Join-Path $runDir 'single-instance-check.json'
$report | ConvertTo-Json -Depth 4 | Set-Content -Path $path -Encoding UTF8
if (-not $report.passed) {
    throw "单实例检查失败：exit=$($second.ExitCode)，启动前宿主数=$($hostsBefore.Count)，启动后宿主数=$($hostsAfter.Count)，已记录激活事件=$activationRecorded。"
}
Write-Host "单实例检查通过，证据：$path"
