function Test-SupervisorAttemptEvidence {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [object[]]$Events,
        [Parameter(Mandatory)]
        [int]$PreviousPid,
        [Parameter(Mandatory)]
        [bool]$ShouldRestart,
        [AllowEmptyString()]
        [string]$ExpectedBackoff
    )

    $events = @($Events)
    $exitIndex = -1
    for ($index = 0; $index -lt $events.Count; $index++) {
        $event = $events[$index]
        if ($event.kind -eq 'supervisor_unexpected_exit' -and $event.pid -eq $PreviousPid) {
            $exitIndex = $index
            break
        }
    }
    if ($exitIndex -lt 0) {
        return [ordered]@{ passed = $false; reason = "未观察到 PID $PreviousPid 的 supervisor_unexpected_exit" }
    }

    $afterExit = @()
    for ($index = $exitIndex + 1; $index -lt $events.Count; $index++) {
        $afterExit += $events[$index]
    }

    if ($ShouldRestart) {
        $backoff = @($afterExit | Where-Object { $_.kind -eq 'supervisor_restart_backoff' -and $_.backoff -eq $ExpectedBackoff }) | Select-Object -First 1
        if ($null -eq $backoff) {
            return [ordered]@{ passed = $false; reason = "未观察到预期退避 $ExpectedBackoff" }
        }
        $agentStarted = @($afterExit | Where-Object { $_.kind -eq 'supervisor_agent_started' -and $_.pid -ne $PreviousPid }) | Select-Object -First 1
        if ($null -eq $agentStarted) {
            return [ordered]@{ passed = $false; reason = '未观察到新的 supervisor_agent_started PID' }
        }
        $healthCheck = @($afterExit | Where-Object { $_.kind -eq 'supervisor_health_check_passed' -and $_.pid -eq $agentStarted.pid }) | Select-Object -First 1
        if ($null -eq $healthCheck) {
            return [ordered]@{ passed = $false; reason = "未观察到重启 PID $($agentStarted.pid) 的 supervisor_health_check_passed" }
        }
        return [ordered]@{
            passed = $true
            reason = ''
            exitedPid = $PreviousPid
            restartedPid = $agentStarted.pid
            observedBackoff = $backoff.backoff
        }
    }

    $limit = @($afterExit | Where-Object { $_.kind -eq 'supervisor_restart_limit_reached' }) | Select-Object -First 1
    if ($null -eq $limit) {
        return [ordered]@{ passed = $false; reason = '未观察到 supervisor_restart_limit_reached' }
    }
    $unexpectedStart = @($afterExit | Where-Object { $_.kind -eq 'supervisor_agent_started' }) | Select-Object -First 1
    if ($null -ne $unexpectedStart) {
        return [ordered]@{ passed = $false; reason = "达到重启上限后仍启动了 PID $($unexpectedStart.pid)" }
    }
    return [ordered]@{ passed = $true; reason = ''; exitedPid = $PreviousPid; restartedPid = 0; observedBackoff = '' }
}

function Wait-SupervisorAttemptEvidence {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string]$EventPath,
        [Parameter(Mandatory)]
        [int]$EventOffset,
        [Parameter(Mandatory)]
        [int]$PreviousPid,
        [Parameter(Mandatory)]
        [bool]$ShouldRestart,
        [AllowEmptyString()]
        [string]$ExpectedBackoff,
        [int]$TimeoutSeconds = 20
    )

    $lastResult = [ordered]@{ passed = $false; reason = '等待守护事件超时' }
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        $allEvents = @()
        if (Test-Path $EventPath) {
            $allEvents = @(Get-Content -LiteralPath $EventPath -Encoding UTF8 | Where-Object { $_ } | ForEach-Object { $_ | ConvertFrom-Json })
        }
        $newEvents = @()
        for ($index = $EventOffset; $index -lt $allEvents.Count; $index++) {
            $newEvents += $allEvents[$index]
        }
        $lastResult = Test-SupervisorAttemptEvidence -Events $newEvents -PreviousPid $PreviousPid -ShouldRestart $ShouldRestart -ExpectedBackoff $ExpectedBackoff
        if ($lastResult.passed) { return $lastResult }
        Start-Sleep -Milliseconds 200
    } while ((Get-Date) -lt $deadline)
    return $lastResult
}
