[CmdletBinding()]
param(
    [ValidateSet('SingleCrash', 'RestartLimit')]
    [string]$Scenario = 'SingleCrash'
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$configPath = Join-Path $root '.spike-run.json'
if (-not (Test-Path $configPath)) { throw '未找到运行配置；先运行 .\scripts\Start-Spike.ps1' }
$config = Get-Content $configPath -Raw | ConvertFrom-Json
$runDir = $config.evidenceDirectory
$baseUri = "http://127.0.0.1:$($config.corePort)"

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

if (-not (Wait-CoreState $true 5)) { throw '开始前测试替身不健康。' }
$crashCount = if ($Scenario -eq 'SingleCrash') { 1 } else { 4 }
$attempts = @()
for ($number = 1; $number -le $crashCount; $number++) {
    if (-not (Wait-CoreState $true 15)) { throw "第 $number 次受控异常前，测试替身没有恢复健康。" }
    Request-ControlledCrash "$Scenario-$number"
    $becameUnhealthy = Wait-CoreState $false 8
    $shouldRestart = $number -lt $crashCount
    $becameHealthy = if ($shouldRestart) { Wait-CoreState $true 20 } else { -not (Wait-CoreState $true 10) }
    $attempts += [ordered]@{
        number = $number
        observedUnhealthy = $becameUnhealthy
        expectedRestart = $shouldRestart
        expectedOutcomeObserved = $becameHealthy
    }
    if (-not $becameUnhealthy -or -not $becameHealthy) {
        throw "第 $number 次受控异常的预期生命周期未出现。请保留日志后停止。"
    }
}

$report = [ordered]@{
    generatedAt = (Get-Date).ToUniversalTime().ToString('o')
    scenario = $Scenario
    attempts = $attempts
    expectedBackoff = if ($Scenario -eq 'RestartLimit') { @('1s', '2s', '4s') } else { @('1s') }
}
$path = Join-Path $runDir ("process-supervisor-$Scenario.json")
$report | ConvertTo-Json -Depth 6 | Set-Content -Path $path -Encoding UTF8
Write-Host "进程守护场景已完成：$path"
