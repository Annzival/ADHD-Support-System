[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$verificationCommit = (& git -C $root rev-parse HEAD).Trim()
$configPath = Join-Path $root '.spike-run.json'
if (-not (Test-Path $configPath)) { throw '未找到运行配置；无法确定要汇总的证据运行。' }
$runDir = (Get-Content $configPath -Raw -Encoding UTF8 | ConvertFrom-Json).evidenceDirectory
$runFile = Join-Path $runDir 'run.json'
if (-not (Test-Path $runFile)) { throw "当前运行目录缺少 run.json：$runDir" }

# The host binary is built before manual checks begin. Evidence-only script
# checkpoints may be newer, so select the active run directory rather than
# requiring its build commit to equal the verifier script commit.
$runs = @(Get-Item -LiteralPath $runDir)
$runMetadata = Get-Content $runFile -Raw -Encoding UTF8 | ConvertFrom-Json
$hostBuildCommit = $runMetadata.commit
$hostStderr = Join-Path $runDir 'host-stderr.log'
$runConfigurationLoaded = $true
$runConfigurationError = ''
if (Test-Path $hostStderr) {
    $hostStderrContents = Get-Content $hostStderr -Raw -Encoding UTF8
    if ($hostStderrContents -match 'read \.spike-run\.json:|parse required \.spike-run\.json:') {
        $runConfigurationLoaded = $false
        $runConfigurationError = '宿主未成功加载 .spike-run.json；锁定的 Python、WebView2 和证据目录配置均未被该运行采用。'
    }
}

$events = @()
$coreEvents = @()
$manual = @()
foreach ($run in $runs) {
    $hostLog = Join-Path $run.FullName 'host-events.jsonl'
    if (Test-Path $hostLog) { $events += Get-Content $hostLog -Encoding UTF8 | Where-Object { $_ } | ForEach-Object { $_ | ConvertFrom-Json } }
    $coreLog = Join-Path $run.FullName 'agent-core-events.jsonl'
    if (Test-Path $coreLog) { $coreEvents += Get-Content $coreLog -Encoding UTF8 | Where-Object { $_ } | ForEach-Object { $_ | ConvertFrom-Json } }
    $manualFile = Join-Path $run.FullName 'manual-observations.json'
    if (Test-Path $manualFile) { $manual += Get-Content $manualFile -Raw -Encoding UTF8 | ConvertFrom-Json }
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
$singleInstanceReportPath = Join-Path $runDir 'single-instance-check.json'
$singleInstanceReport = $null
if (Test-Path $singleInstanceReportPath) {
    $singleInstanceReport = Get-Content $singleInstanceReportPath -Raw -Encoding UTF8 | ConvertFrom-Json
}
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

if (-not $runConfigurationLoaded) {
    # Preserve the raw report for diagnosis, but never turn a fallback-config
    # run into a Windows capability result.
    $tray = 'BLOCKED'
    $overlay = 'BLOCKED'
    $autostart = 'BLOCKED'
    $notification = 'BLOCKED'
    $singleInstance = 'BLOCKED'
    $processSupervisor = 'BLOCKED'
}

$result = [ordered]@{
    generatedAt = (Get-Date).ToUniversalTime().ToString('o')
    hostBuildCommit = $hostBuildCommit
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
        runConfigurationLoaded = $runConfigurationLoaded
        runConfigurationError = $runConfigurationError
    }
    note = '该脚本只汇总 Windows 证据候选；hostBuildCommit 是运行宿主的构建 commit，verificationCommit 是证据脚本 commit。最终 PASS/FAIL/BLOCKED 由 Linux 技术 session 依据返回的证据写入结果文档。'
}
$runsRoot = Join-Path $root '.evidence\runs'
$path = Join-Path $runsRoot ("candidate-results-{0}-{1}.json" -f $hostBuildCommit.Substring(0, 12), $verificationCommit.Substring(0, 12))
$result | ConvertTo-Json -Depth 8 | Set-Content -Path $path -Encoding UTF8
Write-Host "候选证据汇总：$path"
Get-Content $path
if (-not $runConfigurationLoaded) {
    throw $runConfigurationError
}
