[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$RunDirectory
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$candidatePath = Join-Path $RunDirectory 'candidate-results.json'
$processPath = Join-Path $RunDirectory 'process-count.json'
$runPath = Join-Path $RunDirectory 'run.json'
$checkpointPath = Join-Path $root '.evidence\checkpoint\pc-reboot-checkpoint.json'
foreach ($path in @($candidatePath, $processPath, $runPath, $checkpointPath)) {
    if (-not (Test-Path -LiteralPath $path)) {
        throw "Required evidence file is missing: $path"
    }
}

$candidate = Get-Content -LiteralPath $candidatePath -Raw -Encoding UTF8 | ConvertFrom-Json
$processSnapshot = Get-Content -LiteralPath $processPath -Raw -Encoding UTF8 | ConvertFrom-Json
$run = Get-Content -LiteralPath $runPath -Raw -Encoding UTF8 | ConvertFrom-Json
$checkpoint = Get-Content -LiteralPath $checkpointPath -Raw -Encoding UTF8 | ConvertFrom-Json
$preparation = Join-Path $root '.evidence\preparation'
$prepareFile = Get-ChildItem -LiteralPath $preparation -Filter 'synthetic-prepare-*.json' | Sort-Object LastWriteTime | Select-Object -Last 1
if (-not $prepareFile) {
    throw 'Synthetic preparation report is missing.'
}
$prepare = Get-Content -LiteralPath $prepareFile.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
$requiredPreparationChecks = @(
    'synthetic_committed_state_written',
    'synthetic_controlled_abnormal_exit_observed',
    'synthetic_uncommitted_write_rolled_back',
    'synthetic_database_identity_written'
)
$requiredHostChecks = @(
    'first_core_bootstrap_ready',
    'normal_core_exit',
    'second_core_bootstrap_ready',
    'core_restart_reacquired',
    'ordinary_logs_exclude_material'
)
$requiredCoreChecks = @(
    'synthetic_committed_authority_recovered',
    'synthetic_interrupted_write_absent',
    'synthetic_future_action_once',
    'synthetic_expired_not_replayed',
    'synthetic_merged_recovery_once',
    'synthetic_repeat_scan_no_duplicates'
)
$failures = @()
if ($candidate.candidateStatus -ne 'PASS') {
    $failures += "candidateStatus=$($candidate.candidateStatus)"
}
if ($prepare.candidateStatus -ne 'PASS') {
    $failures += "preparation candidateStatus=$($prepare.candidateStatus)"
}
foreach ($name in $requiredPreparationChecks) {
    if ($prepare.checks.$name -ne 'PASS') {
        $failures += "$name=$($prepare.checks.$name)"
    }
}
foreach ($name in $requiredHostChecks) {
    if ($candidate.hostChecks.$name -ne 'PASS') {
        $failures += "$name=$($candidate.hostChecks.$name)"
    }
}
foreach ($name in $requiredCoreChecks) {
    if ($candidate.coreSummary.checks.$name -ne 'PASS') {
        $failures += "$name=$($candidate.coreSummary.checks.$name)"
    }
}
if ($processSnapshot.status -ne 'PASS' -or $processSnapshot.hostCount -ne 1 -or $processSnapshot.coreCount -ne 1) {
    $failures += "host/core process snapshot is invalid: host=$($processSnapshot.hostCount), core=$($processSnapshot.coreCount), status=$($processSnapshot.status)"
}
if ($run.preRestartBootMarker -eq $run.postRestartBootMarker) {
    $failures += 'Windows boot marker did not change.'
}
if ($candidate.coreSummary.databaseIdentity -ne $checkpoint.databaseIdentity) {
    $failures += 'Synthetic database identity did not match the pre-restart checkpoint.'
}
if ($prepare.databaseIdentity -ne $checkpoint.databaseIdentity) {
    $failures += 'Synthetic preparation identity did not match the reboot checkpoint.'
}
if ($candidate.coreSummary.syntheticObservableCounts.futureAction -ne 1 -or $candidate.coreSummary.syntheticObservableCounts.mergedRecoverySignal -ne 1) {
    $failures += 'Synthetic observable counts were not exactly one.'
}
if ($candidate.initialCoreSummary.firstRecoveryScan.futureObservableInserted -ne 1 -or $candidate.initialCoreSummary.firstRecoveryScan.expiredRecordsHandled -ne 1 -or $candidate.initialCoreSummary.firstRecoveryScan.mergedRecoveryInserted -ne 1) {
    $failures += 'Initial recovery scan did not produce exactly the expected synthetic results.'
}
if ($candidate.coreSummary.firstRecoveryScan.futureObservableInserted -ne 0 -or $candidate.coreSummary.firstRecoveryScan.expiredRecordsHandled -ne 0 -or $candidate.coreSummary.firstRecoveryScan.mergedRecoveryInserted -ne 0) {
    $failures += 'Core restart recovery scan repeated a synthetic result.'
}
foreach ($file in Get-ChildItem -LiteralPath $RunDirectory -File -Recurse | Where-Object { $_.Extension -in @('.json', '.jsonl', '.log') }) {
    $raw = [System.IO.File]::ReadAllText($file.FullName)
    if ($raw -match '"token"\s*:' -or $raw -match '"authorization"\s*:' -or $raw -match '"credential"\s*:') {
        $failures += "sensitive field name found in $($file.Name)"
    }
}

$report = [ordered]@{
    schemaVersion = 1
    spike = 'V-03'
    candidateStatus = $candidate.candidateStatus
    preparationCandidateStatus = $prepare.candidateStatus
    preparationChecks = [ordered]@{}
    hostChecks = [ordered]@{}
    coreChecks = [ordered]@{}
    bootMarkerChanged = ($run.preRestartBootMarker -ne $run.postRestartBootMarker)
    processCounts = [ordered]@{ host = $processSnapshot.hostCount; core = $processSnapshot.coreCount }
    databaseIdentityMatchesCheckpoint = ($candidate.coreSummary.databaseIdentity -eq $checkpoint.databaseIdentity)
    initialRecoveryScan = $candidate.initialCoreSummary.firstRecoveryScan
    postNormalExitRecoveryScan = $candidate.coreSummary.firstRecoveryScan
    failureCount = $failures.Count
}
foreach ($name in $requiredHostChecks) {
    $report.hostChecks[$name] = $candidate.hostChecks.$name
}
foreach ($name in $requiredPreparationChecks) {
    $report.preparationChecks[$name] = $prepare.checks.$name
}
foreach ($name in $requiredCoreChecks) {
    $report.coreChecks[$name] = $candidate.coreSummary.checks.$name
}
$report | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $RunDirectory 'validation-report.json') -Encoding UTF8

if ($failures.Count -gt 0) {
    throw ($failures -join [Environment]::NewLine)
}
Write-Host 'Validation evidence: PASS'
