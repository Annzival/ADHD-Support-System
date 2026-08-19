[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$binary = Join-Path $root 'bin\sqlite-restart-recovery.exe'
$markerPath = Join-Path $root '.spike-build.json'
$checkpointPath = Join-Path $root '.evidence\checkpoint\pc-reboot-checkpoint.json'
$databasePath = Join-Path $root '.evidence\state\synthetic-recovery.sqlite'
if (-not (Test-Path -LiteralPath $binary) -or -not (Test-Path -LiteralPath $markerPath)) {
    throw 'Build marker or host binary is missing. Run Build-Spike.ps1 first.'
}
if (-not (Test-Path -LiteralPath $checkpointPath) -or -not (Test-Path -LiteralPath $databasePath)) {
    throw 'Reboot checkpoint or synthetic database is missing. Run Prepare-RebootCheckpoint.ps1 before one real PC restart.'
}

& (Join-Path $PSScriptRoot 'Check-WindowsEnvironment.ps1')
if ($LASTEXITCODE -ne 0) {
    throw 'Environment validation failed; recovery validation was not started.'
}

$checkpoint = Get-Content -LiteralPath $checkpointPath -Raw -Encoding UTF8 | ConvertFrom-Json
$currentCommit = (& git -C $root rev-parse HEAD).Trim()
if ($currentCommit -ne $checkpoint.checkpointCommit) {
    throw "Current commit $currentCommit does not match reboot checkpoint $($checkpoint.checkpointCommit)."
}
if ($checkpoint.databaseRelativePath -ne 'state/synthetic-recovery.sqlite') {
    throw 'Checkpoint does not identify the expected synthetic database location.'
}
$postRestartBootMarker = (Get-CimInstance Win32_OperatingSystem).LastBootUpTime.ToUniversalTime().ToString('o')
if ($postRestartBootMarker -eq $checkpoint.preRestartBootMarker) {
    throw 'Windows boot marker is unchanged. Perform one real PC restart before recovery validation.'
}
$marker = Get-Content -LiteralPath $markerPath -Raw -Encoding UTF8 | ConvertFrom-Json
$actualHostHash = (Get-FileHash -LiteralPath $binary -Algorithm SHA256).Hash
if ($marker.hostBinarySha256 -ne $actualHostHash -or [string]::IsNullOrWhiteSpace($marker.buildCommit)) {
    throw 'Build marker does not match the host binary.'
}

$processName = [System.IO.Path]::GetFileNameWithoutExtension($binary)
if (@(Get-Process -Name $processName -ErrorAction SilentlyContinue).Count -gt 0) {
    throw 'A V-03 host process is already running. Run Cleanup-Spike.ps1 before this validation.'
}
$existingCoreCount = @(Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -and $_.CommandLine -like '*synthetic_core.py*' }).Count
if ($existingCoreCount -gt 0) {
    throw 'A V-03 Core test double is already running. Run Cleanup-Spike.ps1 before this validation.'
}

$versions = Get-Content -LiteralPath (Join-Path $root 'versions.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$runtimeRoot = Join-Path $root ".tools\webview2-fixed-$($versions.candidates.webview2.version)-$($versions.candidates.webview2.architecture)"
$browser = Get-ChildItem -Path $runtimeRoot -Filter 'msedgewebview2.exe' -Recurse | Select-Object -First 1
if (-not $browser) {
    throw 'Fixed Version WebView2 is unavailable.'
}

$pythonExecutable = (& py -3.12 -c 'import sys; print(sys.executable)').Trim()
$verificationCommit = (& git -C $root rev-parse HEAD).Trim()
$runId = "run-{0}-{1}" -f (Get-Date -Format 'yyyyMMddTHHmmssZ'), $verificationCommit.Substring(0, 12)
$runDirectory = Join-Path $root ".evidence\runs\$runId"
New-Item -ItemType Directory -Force -Path $runDirectory | Out-Null
$config = [ordered]@{
    pythonExecutable = $pythonExecutable
    webView2BrowserPath = $browser.DirectoryName
    evidenceDirectory = $runDirectory
    databasePath = $databasePath
    injectedClock = '2030-01-01T10:30:00Z'
    readyHoldMilliseconds = 1800
    handshakeTimeoutMillis = 900
}
[System.IO.File]::WriteAllText((Join-Path $root '.spike-run.json'), ($config | ConvertTo-Json -Depth 5), [System.Text.UTF8Encoding]::new($false))
$run = [ordered]@{
    runId = $runId
    startedAt = (Get-Date).ToUniversalTime().ToString('o')
    checkpointCommit = $checkpoint.checkpointCommit
    verificationScriptCommit = $verificationCommit
    hostBuildCommit = $marker.buildCommit
    hostBinarySha256 = $actualHostHash
    coreSourceSha256 = $marker.coreSourceSha256
    checkpointSha256 = (Get-FileHash -LiteralPath $checkpointPath -Algorithm SHA256).Hash
    preRestartBootMarker = $checkpoint.preRestartBootMarker
    postRestartBootMarker = $postRestartBootMarker
    target = [ordered]@{
        windows = 'Windows 10 22H2 x64'
        wails = $versions.candidates.wails.version
        python = $versions.candidates.python.version
        webview2 = $versions.candidates.webview2.version
    }
}
$run | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $runDirectory 'run.json') -Encoding UTF8

$process = Start-Process -FilePath $binary -WorkingDirectory $root -PassThru -RedirectStandardOutput (Join-Path $runDirectory 'host-stdout.log') -RedirectStandardError (Join-Path $runDirectory 'host-stderr.log')
$hostReadyPath = Join-Path $runDirectory 'host-ready.json'
$deadline = [DateTime]::UtcNow.AddSeconds(20)
while (-not (Test-Path -LiteralPath $hostReadyPath)) {
    if ($process.HasExited) {
        throw "Wails host exited with code $($process.ExitCode) before it was ready. Preserve $runDirectory."
    }
    if ([DateTime]::UtcNow -gt $deadline) {
        throw "Wails host did not reach the ready marker. Preserve $runDirectory."
    }
    Start-Sleep -Milliseconds 100
}

$hostReady = Get-Content -LiteralPath $hostReadyPath -Raw -Encoding UTF8 | ConvertFrom-Json
$hostCount = @(Get-Process -Name $processName -ErrorAction SilentlyContinue).Count
$coreCount = @(Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -and $_.CommandLine -like '*synthetic_core.py*' }).Count
$processSnapshot = [ordered]@{
    hostCount = $hostCount
    coreCount = $coreCount
    hostReady = $hostReady.hostStatus
    status = if ($hostCount -eq 1 -and $coreCount -eq 1 -and $hostReady.hostStatus -eq 'ready') { 'PASS' } else { 'FAIL' }
}
$processSnapshot | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $runDirectory 'process-count.json') -Encoding UTF8

$process.WaitForExit()
if ($process.ExitCode -ne 0) {
    throw "Wails host exited with code $($process.ExitCode). Preserve $runDirectory."
}
& (Join-Path $PSScriptRoot 'Test-ValidationEvidence.ps1') -RunDirectory $runDirectory
if ($LASTEXITCODE -ne 0) {
    throw "Candidate evidence was not accepted. Preserve $runDirectory."
}

Write-Host "Recovery evidence run complete: $runDirectory"
