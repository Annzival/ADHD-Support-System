[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
. (Join-Path (Split-Path -Parent $PSScriptRoot) 'SupervisorEvidence.ps1')

function Assert-Passed([string]$name, [hashtable]$result) {
    if (-not $result.passed) { throw "$name 失败：$($result.reason)" }
}

# Replays the Windows 10 captured fast-restart trace: the HTTP poll missed the
# 0.15s crash window, but the host lifecycle evidence proves the child exited,
# backed off for 1s, started with a new PID, and passed health checking.
$fastRestartEvents = @(
    [pscustomobject]@{ kind = 'supervisor_unexpected_exit'; pid = 28324; restart = 0; backoff = '' },
    [pscustomobject]@{ kind = 'supervisor_restart_backoff'; pid = 0; restart = 1; backoff = '1s' },
    [pscustomobject]@{ kind = 'supervisor_agent_started'; pid = 11108; restart = 0; backoff = '' },
    [pscustomobject]@{ kind = 'supervisor_health_check_passed'; pid = 11108; restart = 0; backoff = '' }
)
$fastRestart = Test-SupervisorAttemptEvidence -Events $fastRestartEvents -PreviousPid 28324 -ShouldRestart $true -ExpectedBackoff '1s'
Assert-Passed -name 'captured fast restart' -result $fastRestart
if ($fastRestart.restartedPid -ne 11108) { throw "captured fast restart PID = $($fastRestart.restartedPid), want 11108" }

$missingBackoff = Test-SupervisorAttemptEvidence -Events @($fastRestartEvents | Where-Object { $_.kind -ne 'supervisor_restart_backoff' }) -PreviousPid 28324 -ShouldRestart $true -ExpectedBackoff '1s'
if ($missingBackoff.passed) { throw 'missing backoff trace was incorrectly accepted' }

$limitEvents = @(
    [pscustomobject]@{ kind = 'supervisor_unexpected_exit'; pid = 11108; restart = 3; backoff = '' },
    [pscustomobject]@{ kind = 'supervisor_restart_limit_reached'; pid = 0; restart = 3; backoff = '' }
)
$limit = Test-SupervisorAttemptEvidence -Events $limitEvents -PreviousPid 11108 -ShouldRestart $false -ExpectedBackoff ''
Assert-Passed -name 'restart limit' -result $limit

Write-Host 'Supervisor evidence replay: OK (captured fast restart and restart limit)'
