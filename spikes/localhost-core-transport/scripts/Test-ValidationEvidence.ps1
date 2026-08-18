[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$RunDirectory
)

$ErrorActionPreference = 'Stop'
$candidatePath = Join-Path $RunDirectory 'candidate-results.json'
if (-not (Test-Path -LiteralPath $candidatePath)) {
    throw 'candidate-results.json was not produced by the host.'
}
$candidate = Get-Content -LiteralPath $candidatePath -Raw -Encoding UTF8 | ConvertFrom-Json
$required = @(
    'loopback_dynamic_endpoint',
    'bootstrap_timeout_is_not_ready',
    'bootstrap_deleted_after_read',
    'authenticated_http_round_trip',
    'authenticated_websocket_round_trip',
    'http_missing_rejected',
    'websocket_missing_rejected',
    'http_incorrect_rejected',
    'websocket_incorrect_rejected',
    'core_unavailable_is_not_ready',
    'old_websocket_invalid_after_restart',
    'new_run_material_changed',
    'http_previous_run_rejected',
    'websocket_previous_run_rejected',
    'reconnected_http_round_trip',
    'reconnected_websocket_round_trip',
    'ordinary_logs_exclude_material'
)

$failures = @()
if ($candidate.candidateStatus -ne 'PASS') {
    $failures += "candidateStatus=$($candidate.candidateStatus)"
}
foreach ($name in $required) {
    if ($candidate.checks.$name -ne 'PASS') {
        $failures += "$($name)=$($candidate.checks.$name)"
    }
}

foreach ($file in Get-ChildItem -LiteralPath $RunDirectory -File -Recurse | Where-Object { $_.Extension -in @('.json', '.jsonl', '.log') }) {
    $raw = [System.IO.File]::ReadAllText($file.FullName)
    if ($raw -match '"token"\s*:' -or $raw -match '"authorization"\s*:') {
        $failures += "sensitive field name found in $($file.Name)"
    }
}

$report = [ordered]@{
    schemaVersion = 1
    candidateStatus = $candidate.candidateStatus
    requiredChecks = [ordered]@{}
    failureCount = $failures.Count
}
foreach ($name in $required) {
    $report.requiredChecks[$name] = $candidate.checks.$name
}
$report | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $RunDirectory 'validation-report.json') -Encoding UTF8

if ($failures.Count -gt 0) {
    throw ($failures -join [Environment]::NewLine)
}
Write-Host 'Validation evidence: PASS'
