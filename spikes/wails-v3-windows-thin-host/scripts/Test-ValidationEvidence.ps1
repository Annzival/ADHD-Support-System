[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$commit = (& git -C $root rev-parse HEAD).Trim()
$runsRoot = Join-Path $root '.evidence\runs'
if (-not (Test-Path $runsRoot)) { throw '未找到任何证据运行目录。' }

$runs = Get-ChildItem -Path $runsRoot -Directory | Where-Object {
    $runFile = Join-Path $_.FullName 'run.json'
    (Test-Path $runFile) -and ((Get-Content $runFile -Raw | ConvertFrom-Json).commit -eq $commit)
}
if ($runs.Count -eq 0) { throw "未找到当前 commit $commit 的证据运行。" }

$events = @()
$coreEvents = @()
$manual = @()
foreach ($run in $runs) {
    $hostLog = Join-Path $run.FullName 'host-events.jsonl'
    if (Test-Path $hostLog) { $events += Get-Content $hostLog | Where-Object { $_ } | ForEach-Object { $_ | ConvertFrom-Json } }
    $coreLog = Join-Path $run.FullName 'agent-core-events.jsonl'
    if (Test-Path $coreLog) { $coreEvents += Get-Content $coreLog | Where-Object { $_ } | ForEach-Object { $_ | ConvertFrom-Json } }
    $manualFile = Join-Path $run.FullName 'manual-observations.json'
    if (Test-Path $manualFile) { $manual += Get-Content $manualFile -Raw | ConvertFrom-Json }
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
$singleInstance = if ((Has-Event 'second_instance_activated')) { 'PASS' } else { 'BLOCKED' }
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
    commit = $commit
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
    }
    note = '该脚本只汇总 Windows 证据候选；最终 PASS/FAIL/BLOCKED 由 Linux 技术 session 依据返回的证据写入结果文档。'
}
$path = Join-Path $runsRoot ("candidate-results-{0}.json" -f $commit.Substring(0, 12))
$result | ConvertTo-Json -Depth 8 | Set-Content -Path $path -Encoding UTF8
Write-Host "候选证据汇总：$path"
Get-Content $path
