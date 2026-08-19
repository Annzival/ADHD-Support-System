[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$markerPath = Join-Path $root '.spike-build.json'
$databasePath = Join-Path $root '.evidence\state\synthetic-recovery.sqlite'
$checkpointDirectory = Join-Path $root '.evidence\checkpoint'
$checkpointPath = Join-Path $checkpointDirectory 'pc-reboot-checkpoint.json'
$preparation = Join-Path $root '.evidence\preparation'
if (-not (Test-Path -LiteralPath $markerPath)) {
    throw 'Build marker is missing. Run Build-Spike.ps1 first.'
}
if ((Test-Path -LiteralPath $databasePath) -or (Test-Path -LiteralPath $checkpointPath)) {
    throw 'A V-03 checkpoint already exists. Preserve it; do not overwrite an attempt.'
}

$marker = Get-Content -LiteralPath $markerPath -Raw -Encoding UTF8 | ConvertFrom-Json
$pythonExecutable = (& py -3.12 -c 'import sys; print(sys.executable)').Trim()
$summaryPath = Join-Path $preparation ("synthetic-prepare-{0}.json" -f (Get-Date -Format 'yyyyMMddTHHmmssZ'))
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $databasePath) | Out-Null
& $pythonExecutable (Join-Path $root 'agent_core\synthetic_core.py') '--mode' 'prepare' '--database' $databasePath '--summary-file' $summaryPath
if ($LASTEXITCODE -ne 0) {
    throw "Synthetic checkpoint preparation failed with exit code $LASTEXITCODE."
}
$summary = Get-Content -LiteralPath $summaryPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($summary.candidateStatus -ne 'PASS') {
    throw "Synthetic checkpoint candidateStatus=$($summary.candidateStatus)."
}
$bootMarker = (Get-CimInstance Win32_OperatingSystem).LastBootUpTime.ToUniversalTime().ToString('o')
$checkpoint = [ordered]@{
    schemaVersion = 1
    spike = 'V-03'
    checkpointCommit = (& git -C $root rev-parse HEAD).Trim()
    preparedAt = (Get-Date).ToUniversalTime().ToString('o')
    preRestartBootMarker = $bootMarker
    databaseIdentity = $summary.databaseIdentity
    databaseFileSha256 = $summary.databaseFileSha256
    databaseRelativePath = 'state/synthetic-recovery.sqlite'
    prepareSummarySha256 = (Get-FileHash -LiteralPath $summaryPath -Algorithm SHA256).Hash
    hostBuildCommit = $marker.buildCommit
    hostBinarySha256 = $marker.hostBinarySha256
    coreSourceSha256 = $marker.coreSourceSha256
}
New-Item -ItemType Directory -Force -Path $checkpointDirectory | Out-Null
[System.IO.File]::WriteAllText($checkpointPath, ($checkpoint | ConvertTo-Json -Depth 8), [System.Text.UTF8Encoding]::new($false))
Write-Host "Prepared synthetic checkpoint: $checkpointPath"
Write-Host 'Checkpoint is safe to restart. Perform one real PC restart before running Start-RecoveryValidation.ps1.'
