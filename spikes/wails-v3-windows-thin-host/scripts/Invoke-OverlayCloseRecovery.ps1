[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$configPath = Join-Path $root '.spike-run.json'
if (-not (Test-Path -LiteralPath $configPath)) {
    throw '未找到运行配置；先运行 .\scripts\Start-Spike.ps1。'
}

$config = Get-Content -LiteralPath $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
$runDir = [string]$config.evidenceDirectory
$hostEventPath = Join-Path $runDir 'host-events.jsonl'
if (-not (Test-Path -LiteralPath $hostEventPath)) {
    throw '当前运行没有 host-events.jsonl；宿主必须先成功加载运行配置。'
}

$binary = Join-Path $root 'bin\wails-v3-windows-thin-host.exe'
$hostProcessName = [System.IO.Path]::GetFileNameWithoutExtension($binary)
$coreScript = Join-Path $root 'agent_core\agent_core_stub.py'
$corePort = [int]$config.corePort
$verificationCommit = (& git -C $root rev-parse HEAD).Trim()

function Get-HostEvents {
    return @(
        Get-Content -LiteralPath $hostEventPath -Encoding UTF8 |
            Where-Object { $_ } |
            ForEach-Object { $_ | ConvertFrom-Json }
    )
}

function Get-EventsAfter {
    param([int]$Offset)

    $events = @(Get-HostEvents)
    if ($Offset -ge $events.Count) {
        return @()
    }
    return @($events[$Offset..($events.Count - 1)])
}

function Get-EventCount {
    return @(Get-HostEvents).Count
}

function Test-EventSince {
    param(
        [int]$Offset,
        [string]$Kind
    )

    return @((Get-EventsAfter -Offset $Offset) | Where-Object { $_.kind -eq $Kind }).Count -gt 0
}

function Get-CoreHealth {
    try {
        $health = Invoke-RestMethod -Uri ("http://127.0.0.1:{0}/health" -f $corePort) -TimeoutSec 3
        return $health.status -eq 'ok'
    }
    catch {
        return $false
    }
}

function Get-ProcessSnapshot {
    $hosts = @(Get-Process -Name $hostProcessName -ErrorAction SilentlyContinue)
    $cores = @(
        Get-CimInstance -ClassName Win32_Process |
            Where-Object { $_.CommandLine -like "*$coreScript*" }
    )
    return [ordered]@{
        hostCount = $hosts.Count
        coreCount = $cores.Count
        coreHealth = Get-CoreHealth
    }
}

function Get-SnapshotStatus {
    param($Snapshot)

    if ($Snapshot.hostCount -eq 1 -and $Snapshot.coreCount -eq 1 -and $Snapshot.coreHealth) {
        return 'PASS'
    }
    return 'FAIL'
}

function Ask-Observation {
    param(
        [string]$ID,
        [string]$Instruction,
        [string]$Question
    )

    Write-Host ''
    Write-Host "[$ID] $Instruction" -ForegroundColor Cyan
    $null = Read-Host '完成后按 Enter'
    do {
        $result = (Read-Host "$Question 输入 PASS / FAIL / BLOCKED").Trim().ToUpperInvariant()
    } while ($result -notin @('PASS', 'FAIL', 'BLOCKED'))
    return $result
}

function Combine-Status {
    param([string[]]$Values)

    if ($Values -contains 'FAIL') {
        return 'FAIL'
    }
    if ($Values -contains 'BLOCKED') {
        return 'BLOCKED'
    }
    return 'PASS'
}

$rounds = @()
for ($round = 1; $round -le 3; $round++) {
    $roundStart = Get-EventCount
    $showBeforeOffset = Get-EventCount
    $shownBeforeClose = Ask-Observation -ID "R$round-show" -Instruction '从托盘选择“显示置顶演示小窗”，切换到一个普通窗口，确认小窗可见且仍在其上方。' -Question '显示且置顶的观察结果是？'
    $showBeforeLogged = Test-EventSince -Offset $showBeforeOffset -Kind 'overlay_shown'

    $closeOffset = Get-EventCount
    $hiddenOnNativeClose = Ask-Observation -ID "R$round-close" -Instruction '在小窗原生标题栏点击叉号，确认小窗隐藏，托盘图标仍存在；不要退出宿主。' -Question '原生关闭转隐藏、宿主/托盘继续运行的观察结果是？'
    $hiddenOnCloseLogged = Test-EventSince -Offset $closeOffset -Kind 'overlay_hidden_on_close'
    $afterCloseSnapshot = Get-ProcessSnapshot

    $showAfterOffset = Get-EventCount
    $shownAfterClose = Ask-Observation -ID "R$round-reopen" -Instruction '再次从托盘选择“显示置顶演示小窗”，确认同一小窗可见且仍在普通窗口上方。' -Question '再次显示且置顶的观察结果是？'
    $showAfterLogged = Test-EventSince -Offset $showAfterOffset -Kind 'overlay_shown'
    $destroyedBeforeShow = Test-EventSince -Offset $roundStart -Kind 'overlay_destroyed_before_show'

    $automaticStatus = Get-SnapshotStatus -Snapshot $afterCloseSnapshot
    $loggingStatus = if ($showBeforeLogged -and $hiddenOnCloseLogged -and $showAfterLogged -and -not $destroyedBeforeShow) {
        'PASS'
    } else {
        'BLOCKED'
    }
    $roundStatus = Combine-Status -Values @(
        $shownBeforeClose,
        $hiddenOnNativeClose,
        $shownAfterClose,
        $automaticStatus,
        $loggingStatus
    )
    $rounds += [ordered]@{
        round = $round
        observedAt = (Get-Date).ToUniversalTime().ToString('o')
        manual = [ordered]@{
            shownBeforeNativeClose = $shownBeforeClose
            hiddenOnNativeClose = $hiddenOnNativeClose
            shownAfterNativeClose = $shownAfterClose
        }
        automatic = [ordered]@{
            overlayShownBeforeCloseLogged = $showBeforeLogged
            overlayHiddenOnCloseLogged = $hiddenOnCloseLogged
            overlayShownAfterCloseLogged = $showAfterLogged
            unexpectedDestructionLogged = $destroyedBeforeShow
            postCloseProcessSnapshot = $afterCloseSnapshot
        }
        status = $roundStatus
    }
}

$trayHideOffset = Get-EventCount
$trayHidden = Ask-Observation -ID 'tray-hide' -Instruction '完成三轮后，从托盘选择“隐藏置顶演示小窗”，确认小窗隐藏且宿主继续运行。' -Question '托盘隐藏的观察结果是？'
$trayHiddenLogged = Test-EventSince -Offset $trayHideOffset -Kind 'overlay_hidden'

$trayShowOffset = Get-EventCount
$trayShown = Ask-Observation -ID 'tray-show' -Instruction '从托盘再次选择“显示置顶演示小窗”，确认小窗可见且仍在普通窗口上方。' -Question '托盘再次显示且置顶的观察结果是？'
$trayShownLogged = Test-EventSince -Offset $trayShowOffset -Kind 'overlay_shown'
$finalSnapshot = Get-ProcessSnapshot
$unexpectedDestructions = @((Get-HostEvents) | Where-Object { $_.kind -eq 'overlay_destroyed_before_show' }).Count
$trayLoggingStatus = if ($trayHiddenLogged -and $trayShownLogged -and $unexpectedDestructions -eq 0) { 'PASS' } else { 'BLOCKED' }
$trayStatus = Combine-Status -Values @(
    $trayHidden,
    $trayShown,
    (Get-SnapshotStatus -Snapshot $finalSnapshot),
    $trayLoggingStatus
)
$overallStatus = Combine-Status -Values (@($rounds | ForEach-Object { $_.status }) + @($trayStatus))

$assessment = [ordered]@{
    schemaVersion = 1
    spike = 'V-01R'
    generatedAt = (Get-Date).ToUniversalTime().ToString('o')
    verificationCommit = $verificationCommit
    runId = Split-Path -Leaf $runDir
    rounds = $rounds
    trayHideShowAfterRounds = [ordered]@{
        manual = [ordered]@{
            hidden = $trayHidden
            shownAndTopmost = $trayShown
        }
        automatic = [ordered]@{
            overlayHiddenLogged = $trayHiddenLogged
            overlayShownLogged = $trayShownLogged
            unexpectedDestructionCount = $unexpectedDestructions
            processSnapshot = $finalSnapshot
        }
        status = $trayStatus
    }
    overallStatus = $overallStatus
    note = 'PASS 只表示该脚本收集到的 Windows 实机观察和日志满足 V-01R 条件；最终结论仍由收到证据的技术 session 写入结果文档。'
}
$assessmentPath = Join-Path $runDir 'overlay-close-recovery.json'
$assessment | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $assessmentPath -Encoding UTF8
Write-Host "逐轮复验证据已保存：$assessmentPath"
Get-Content -LiteralPath $assessmentPath -Encoding UTF8

if ($overallStatus -ne 'PASS') {
    Write-Error "V-01R 复验结果为 $overallStatus；不要修改代码重试。仍请运行 Collect-OverlayCloseRecoveryEvidence.ps1 回传证据。"
    exit 1
}
