[CmdletBinding()]
param(
    [ValidateSet('SingleCrash', 'RestartLimit')]
    [string]$Scenario = 'SingleCrash'
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'SupervisorEvidence.ps1')
$configPath = Join-Path $root '.spike-run.json'
if (-not (Test-Path $configPath)) { throw '未找到运行配置；先运行 .\scripts\Start-Spike.ps1' }
$config = Get-Content $configPath -Raw | ConvertFrom-Json
$runDir = $config.evidenceDirectory
$baseUri = "http://127.0.0.1:$($config.corePort)"
$hostEventPath = Join-Path $runDir 'host-events.jsonl'

function Test-CoreHealthy {
    try {
        return (Invoke-RestMethod -Uri "$baseUri/health" -TimeoutSec 2).status -eq 'ok'
    } catch {
        return $false
    }
}

function Wait-CoreState([bool]$expected, [int]$timeoutSeconds) {
    $deadline = (Get-Date).AddSeconds($timeoutSeconds)
    do {
        if ((Test-CoreHealthy) -eq $expected) { return $true }
        Start-Sleep -Milliseconds 200
    } while ((Get-Date) -lt $deadline)
    return $false
}

function Request-ControlledCrash([string]$label) {
    Invoke-RestMethod -Method Post -Uri "$baseUri/control/crash" -ContentType 'application/json' -Body (@{ scenario = $label } | ConvertTo-Json -Compress) -TimeoutSec 2 | Out-Null
}

function Get-HostEvents {
    if (-not (Test-Path $hostEventPath)) { throw "未找到宿主事件日志：$hostEventPath" }
    return @(Get-Content -LiteralPath $hostEventPath -Encoding UTF8 | Where-Object { $_ } | ForEach-Object { $_ | ConvertFrom-Json })
}

function Get-CurrentCorePid([object[]]$events) {
    $healthy = @($events | Where-Object { $_.kind -eq 'supervisor_health_check_passed' }) | Select-Object -Last 1
    if ($null -eq $healthy -or $healthy.pid -le 0) { throw '未从宿主事件日志找到当前健康测试替身 PID。' }
    return [int]$healthy.pid
}

if (-not (Wait-CoreState $true 5)) { throw '开始前测试替身不健康。' }
$crashCount = if ($Scenario -eq 'SingleCrash') { 1 } else { 4 }
$attempts = @()
$failure = ''
for ($number = 1; $number -le $crashCount; $number++) {
    if (-not (Wait-CoreState $true 15)) { throw "第 $number 次受控异常前，测试替身没有恢复健康。" }
    $eventsBeforeCrash = Get-HostEvents
    $eventOffset = $eventsBeforeCrash.Count
    $previousPid = Get-CurrentCorePid $eventsBeforeCrash
    Request-ControlledCrash "$Scenario-$number"
    # A single controlled crash is specifically the restart case. In the
    # restart-limit scenario only the fourth crash must remain stopped.
    $shouldRestart = ($Scenario -eq 'SingleCrash') -or ($number -lt $crashCount)
    $expectedBackoff = if ($shouldRestart) { "$([int][Math]::Pow(2, $number - 1))s" } else { '' }
    # /health may skip a sub-second port gap between exit and restart. The
    # host's ordered lifecycle log is the primary evidence; HTTP remains only
    # a pre-crash readiness guard above.
    $eventEvidence = Wait-SupervisorAttemptEvidence -EventPath $hostEventPath -EventOffset $eventOffset -PreviousPid $previousPid -ShouldRestart $shouldRestart -ExpectedBackoff $expectedBackoff -TimeoutSeconds 20
    $attempts += [ordered]@{
        number = $number
        previousPid = $previousPid
        expectedRestart = $shouldRestart
        expectedBackoff = $expectedBackoff
        eventEvidence = $eventEvidence
        expectedOutcomeObserved = $eventEvidence.passed
    }
    if (-not $eventEvidence.passed) {
        $failure = "第 $number 次受控异常的守护事件链不完整：$($eventEvidence.reason)"
        break
    }
}

$report = [ordered]@{
    generatedAt = (Get-Date).ToUniversalTime().ToString('o')
    scenario = $Scenario
    attempts = $attempts
    expectedBackoff = if ($Scenario -eq 'RestartLimit') { @('1s', '2s', '4s') } else { @('1s') }
    passed = [string]::IsNullOrEmpty($failure)
    failure = $failure
}
$path = Join-Path $runDir ("process-supervisor-$Scenario.json")
$report | ConvertTo-Json -Depth 6 | Set-Content -Path $path -Encoding UTF8
if (-not [string]::IsNullOrEmpty($failure)) {
    throw "$failure 请保留日志和 $path 后停止。"
}
Write-Host "进程守护场景已完成：$path"
