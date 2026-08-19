[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$RunDirectory
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
& (Join-Path $PSScriptRoot 'Test-ValidationEvidence.ps1') -RunDirectory $RunDirectory
if ($LASTEXITCODE -ne 0) {
    throw 'Candidate evidence failed validation and was not collected.'
}

$run = Get-Content -LiteralPath (Join-Path $RunDirectory 'run.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$candidate = Get-Content -LiteralPath (Join-Path $RunDirectory 'candidate-results.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$validation = Get-Content -LiteralPath (Join-Path $RunDirectory 'validation-report.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$processSnapshot = Get-Content -LiteralPath (Join-Path $RunDirectory 'process-count.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$checkpointPath = Join-Path $root '.evidence\checkpoint\pc-reboot-checkpoint.json'
$checkpoint = Get-Content -LiteralPath $checkpointPath -Raw -Encoding UTF8 | ConvertFrom-Json
$preparation = Join-Path $root '.evidence\preparation'
$environmentFile = Get-ChildItem -LiteralPath $preparation -Filter 'environment-*.json' | Sort-Object LastWriteTime | Select-Object -Last 1
$buildFile = Get-ChildItem -LiteralPath $preparation -Filter 'build-*.json' | Sort-Object LastWriteTime | Select-Object -Last 1
$staticFile = Get-ChildItem -LiteralPath $preparation -Filter 'static-contract-*.json' | Sort-Object LastWriteTime | Select-Object -Last 1
$prepareFile = Get-ChildItem -LiteralPath $preparation -Filter 'synthetic-prepare-*.json' | Sort-Object LastWriteTime | Select-Object -Last 1
if (-not $environmentFile -or -not $buildFile -or -not $staticFile -or -not $prepareFile) {
    throw 'Environment, build, static-contract, or synthetic preparation report is missing.'
}
$environment = Get-Content -LiteralPath $environmentFile.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
$prepare = Get-Content -LiteralPath $prepareFile.FullName -Raw -Encoding UTF8 | ConvertFrom-Json

$packageRoot = Join-Path $root '.evidence\packages'
New-Item -ItemType Directory -Force -Path $packageRoot | Out-Null
$artifactPaths = @(
    (Get-ChildItem -LiteralPath $RunDirectory -File -Recurse | Select-Object -ExpandProperty FullName),
    $checkpointPath,
    $environmentFile.FullName,
    $buildFile.FullName,
    $staticFile.FullName,
    $prepareFile.FullName
) | Where-Object { Test-Path -LiteralPath $_ }
$sourceArtifacts = @($artifactPaths | ForEach-Object {
    [ordered]@{
        fileName = [System.IO.Path]::GetFileName($_)
        sha256 = (Get-FileHash -LiteralPath $_ -Algorithm SHA256).Hash
    }
})
$manifest = [ordered]@{
    schemaVersion = 1
    spike = 'V-03'
    runId = $run.runId
    checkpointCommit = $run.checkpointCommit
    verificationScriptCommit = $run.verificationScriptCommit
    sourceArtifacts = $sourceArtifacts
}
$manifestPath = Join-Path $packageRoot ("v03-return-manifest-{0}.json" -f $run.verificationScriptCommit.Substring(0, 12))
$manifest | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $manifestPath -Encoding UTF8
$archive = Join-Path $packageRoot ("v03-windows-pc-restart-evidence-{0}-{1}.zip" -f $run.verificationScriptCommit.Substring(0, 12), (Get-Date -Format 'yyyyMMddTHHmmssZ'))
Compress-Archive -Path @($RunDirectory, $checkpointPath, $manifestPath) -DestinationPath $archive -CompressionLevel Optimal
$archiveHash = ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash).ToLowerInvariant()

$summary = [ordered]@{
    schemaVersion = 1
    spike = 'V-03'
    phase = 'windows_pc_restart_candidate'
    finalStatusCandidate = $candidate.candidateStatus
    sanitization = [ordered]@{
        contains = @('synthetic record identifiers', 'capability status', 'version strings', 'commit IDs', 'boot marker comparison', 'process counts', 'SHA-256')
        excluded = @('absolute paths', 'Windows account names', 'process IDs', 'temporary token values', 'Authorization headers', 'raw log bodies', 'SQLite database bytes', 'screenshots and recordings')
        rawArchiveCommitted = $false
    }
    targetEnvironment = [ordered]@{
        windows = $environment.actual.windows
        tools = [ordered]@{
            go = $environment.actual.go.version
            python = $environment.actual.python
            wails = $environment.actual.wails.version
            webview2 = $environment.actual.webview2.version
        }
    }
    build = [ordered]@{
        checkpointCommit = $run.checkpointCommit
        implementationCommit = $run.hostBuildCommit
        verificationScriptCommit = $run.verificationScriptCommit
        hostBinarySha256 = $run.hostBinarySha256
        coreSourceSha256 = $run.coreSourceSha256
    }
    pcRestart = [ordered]@{
        bootMarkerChanged = $validation.bootMarkerChanged
        hostCount = $processSnapshot.hostCount
        coreCount = $processSnapshot.coreCount
    }
    syntheticPreparation = [ordered]@{
        candidateStatus = $prepare.candidateStatus
        checks = $prepare.checks
        databaseIdentity = $prepare.databaseIdentity
    }
    recovery = [ordered]@{
        validation = $validation
        hostChecks = $candidate.hostChecks
        coreSummary = $candidate.coreSummary
    }
    sourceArtifacts = $sourceArtifacts
    rawEvidenceArchive = [ordered]@{
        fileName = [System.IO.Path]::GetFileName($archive)
        sha256 = $archiveHash
        controlledLocation = 'Windows working copy under spikes/sqlite-restart-recovery/.evidence/packages; absolute path omitted.'
        accessProcedure = 'Return the archive through the agreed private channel, then verify this SHA-256 before review.'
        retention = 'Retain until Issue #18 and its Draft PR have completed review; do not commit the raw archive or publish it.'
    }
}
$summaryPath = Join-Path $packageRoot ("v03-evidence-summary-{0}.json" -f $run.verificationScriptCommit.Substring(0, 12))
[System.IO.File]::WriteAllText($summaryPath, ($summary | ConvertTo-Json -Depth 20), [System.Text.UTF8Encoding]::new($false))

Write-Host "Sanitized summary: $summaryPath"
Write-Host "Raw evidence archive SHA-256: $archiveHash"
Write-Host 'Return the summary and archive through the agreed private channel.'
