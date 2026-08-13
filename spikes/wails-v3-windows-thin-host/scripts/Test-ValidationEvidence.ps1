[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$verificationCommit = (& git -C $root rev-parse HEAD).Trim()
$runsRoot = Join-Path $root '.evidence\runs'
if (-not (Test-Path $runsRoot)) { throw '未找到任何证据运行目录。' }

# A and B deliberately use separate host runs. Select every run that proves
# the host wrote into its configured directory, while excluding old diagnostic
# runs whose host stderr proves that .spike-run.json was not loaded.
$runs = @()
$excludedRuns = @()
foreach ($candidate in @(Get-ChildItem -LiteralPath $runsRoot -Directory | Sort-Object Name)) {
    $runFile = Join-Path $candidate.FullName 'run.json'
    $hostLog = Join-Path $candidate.FullName 'host-events.jsonl'
    $hostStderr = Join-Path $candidate.FullName 'host-stderr.log'
    if (-not (Test-Path $runFile) -or -not (Test-Path $hostLog)) { continue }
    $stderrText = if (Test-Path $hostStderr) { Get-Content $hostStderr -Raw -Encoding UTF8 } else { '' }
    if ($stderrText -match 'read \.spike-run\.json:|parse required \.spike-run\.json:') {
        $excludedRuns += [ordered]@{ path = $candidate.FullName; reason = '宿主未加载 .spike-run.json' }
    } else {
        $runs += $candidate
    }
}
if ($runs.Count -eq 0) { throw '没有配置加载成功且包含宿主事件日志的运行；无法汇总 Windows 证据。' }
$hostBuildCommits = @($runs | ForEach-Object { (Get-Content (Join-Path $_.FullName 'run.json') -Raw -Encoding UTF8 | ConvertFrom-Json).commit } | Sort-Object -Unique)

$events = @()
$coreEvents = @()
$manual = @()
$singleInstanceReports = @()
foreach ($run in $runs) {
    $hostLog = Join-Path $run.FullName 'host-events.jsonl'
    if (Test-Path $hostLog) { $events += Get-Content $hostLog -Encoding UTF8 | Where-Object { $_ } | ForEach-Object { $_ | ConvertFrom-Json } }
    $coreLog = Join-Path $run.FullName 'agent-core-events.jsonl'
    if (Test-Path $coreLog) { $coreEvents += Get-Content $coreLog -Encoding UTF8 | Where-Object { $_ } | ForEach-Object { $_ | ConvertFrom-Json } }
    $manualFile = Join-Path $run.FullName 'manual-observations.json'
    if (Test-Path $manualFile) { $manual += Get-Content $manualFile -Raw -Encoding UTF8 | ConvertFrom-Json }
    $singleInstanceReportPath = Join-Path $run.FullName 'single-instance-check.json'
    if (Test-Path $singleInstanceReportPath) {
        $singleInstanceReports += [ordered]@{
            run = $run.FullName
            report = Get-Content $singleInstanceReportPath -Raw -Encoding UTF8 | ConvertFrom-Json
        }
    }
}

function Has-Event([string]$kind) { return @($events | Where-Object { $_.kind -eq $kind }).Count -gt 0 }
function Manual-Result([string]$id) {
    $matching = @($manual | Where-Object { $_.id -eq $id })
    if ($matching.Count -eq 0) { return 'BLOCKED' }
    return $matching[-1].result
}
function Combined([string[]]$values) {
    if ($values -contains 'FAIL') { return 'FAIL' }
    if ($values -contains 'BLOCKED') { return 'BLOCKED' }
    return 'PASS'
}

$backoffs = @($events | Where-Object { $_.kind -eq 'supervisor_restart_backoff' } | ForEach-Object { $_.backoff })
$notificationCore = @($coreEvents | Where-Object { $_.kind -eq 'notification_context_received' }).Count -gt 0
$binary = Join-Path $root 'bin\wails-v3-windows-thin-host.exe'
$coreScript = Join-Path $root 'agent_core\agent_core_stub.py'
$hostProcesses = @(Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -eq $binary })
$coreProcesses = @(Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like "*$coreScript*" })
$orphan = if ($hostProcesses.Count -eq 0 -and $coreProcesses.Count -eq 0) { 'PASS' } else { 'BLOCKED' }

$tray = Combined @((Manual-Result 'tray_close_keeps_host'), (Manual-Result 'tray_restores_main'))
$overlay = Combined @((Manual-Result 'overlay_show_hide'), (Manual-Result 'overlay_stays_on_top'))
$autostartEnabled = if ((Has-Event 'autostart_enabled')) { 'PASS' } else { 'BLOCKED' }
$autostartDisabled = if ((Has-Event 'autostart_disabled')) { 'PASS' } else { 'BLOCKED' }
$autostart = Combined @((Manual-Result 'autostart_real_login'), $autostartEnabled, $autostartDisabled)
$notificationSent = if ((Has-Event 'notification_sent')) { 'PASS' } else { 'BLOCKED' }
$notificationResponse = if ((Has-Event 'notification_response_received')) { 'PASS' } else { 'BLOCKED' }
$notificationRoute = if ((Has-Event 'notification_context_routed') -and $notificationCore) { 'PASS' } else { 'BLOCKED' }
$notification = Combined @((Manual-Result 'notification_action_activates_context'), $notificationSent, $notificationResponse, $notificationRoute)
$singleInstanceReport = if ($singleInstanceReports.Count -gt 0) { $singleInstanceReports[-1].report } else { $null }
$singleInstance = if ($null -eq $singleInstanceReport) {
    'BLOCKED'
} elseif ($singleInstanceReport.passed -eq $true) {
    'PASS'
} else {
    'FAIL'
}
$supervisorLifecycle = if (
    (Has-Event 'supervisor_health_check_passed') -and
    (Has-Event 'supervisor_unexpected_exit') -and
    (Has-Event 'supervisor_restart_limit_reached') -and
    ($backoffs -contains '1s') -and
    ($backoffs -contains '2s') -and
    ($backoffs -contains '4s')
) { 'PASS' } else { 'BLOCKED' }
$supervisorExplicitExit = if ((Has-Event 'supervisor_explicit_stop_completed')) { 'PASS' } else { 'BLOCKED' }
$processSupervisor = Combined @($supervisorLifecycle, $supervisorExplicitExit, $orphan)

$result = [ordered]@{
    generatedAt = (Get-Date).ToUniversalTime().ToString('o')
    hostBuildCommits = $hostBuildCommits
    verificationCommit = $verificationCommit
    includedRuns = @($runs.FullName)
    candidateResults = [ordered]@{
        tray = $tray
        overlay = $overlay
        autostart = $autostart
        notification = $notification
        singleInstance = $singleInstance
        processSupervisor = $processSupervisor
        hostBoundary = 'BLOCKED'
    }
    automaticEvidence = [ordered]@{
        eventKinds = @($events | ForEach-Object { $_.kind } | Sort-Object -Unique)
        observedBackoffs = $backoffs
        notificationContextReachedCore = $notificationCore
        currentHostProcessCount = $hostProcesses.Count
        currentCoreProcessCount = $coreProcesses.Count
        orphanCheck = $orphan
        singleInstanceReport = $singleInstanceReport
        singleInstanceReports = $singleInstanceReports
        excludedRuns = $excludedRuns
    }
    note = '该脚本汇总所有配置已成功加载的 A/B 运行；hostBuildCommits 是各运行宿主的构建 commit，verificationCommit 是证据脚本 commit。最终 PASS/FAIL/BLOCKED 由 Linux 技术 session 依据返回的证据写入结果文档。'
}
$path = Join-Path $runsRoot ("candidate-results-{0}.json" -f $verificationCommit.Substring(0, 12))
$result | ConvertTo-Json -Depth 8 | Set-Content -Path $path -Encoding UTF8
Write-Host "候选证据汇总：$path"
Get-Content $path
