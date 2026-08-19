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
$versions = Get-Content -LiteralPath (Join-Path $root 'versions.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$preparation = Join-Path $root '.evidence\preparation'
$environmentFile = Get-ChildItem -LiteralPath $preparation -Filter 'environment-*.json' | Sort-Object LastWriteTime | Select-Object -Last 1
$buildFile = Get-ChildItem -LiteralPath $preparation -Filter 'build-*.json' | Sort-Object LastWriteTime | Select-Object -Last 1
$staticFile = Get-ChildItem -LiteralPath $preparation -Filter 'static-contract-*.json' | Sort-Object LastWriteTime | Select-Object -Last 1
if (-not $environmentFile -or -not $buildFile -or -not $staticFile) {
    throw 'Environment, build, or static-contract report is missing.'
}
$environment = Get-Content -LiteralPath $environmentFile.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
$build = Get-Content -LiteralPath $buildFile.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
$pythonCheck = $environment.checks.python_3_12_3_x64
if ($null -eq $pythonCheck -or $null -eq $environment.actual.python -or $null -eq $environment.actual.python.processBits) {
    throw 'Python x64 environment evidence is missing.'
}
$pythonProcessBits = [int]$environment.actual.python.processBits
if (-not [bool]$pythonCheck.passed -or $pythonProcessBits -ne ([int]$versions.candidates.python.processBits)) {
    throw "Python process bitness did not satisfy the locked requirement: expected $($versions.candidates.python.processBits), actual $pythonProcessBits."
}

$packageRoot = Join-Path $root '.evidence\packages'
New-Item -ItemType Directory -Force -Path $packageRoot | Out-Null
$artifactPaths = @(
    (Join-Path $RunDirectory 'run.json'),
    (Join-Path $RunDirectory 'candidate-results.json'),
    (Join-Path $RunDirectory 'validation-report.json'),
    (Join-Path $RunDirectory 'host-events.jsonl'),
    (Join-Path $RunDirectory 'core-events.jsonl'),
    $environmentFile.FullName,
    $buildFile.FullName,
    $staticFile.FullName
) | Where-Object { Test-Path -LiteralPath $_ }
$sourceArtifacts = @($artifactPaths | ForEach-Object {
    [ordered]@{
        fileName = [System.IO.Path]::GetFileName($_)
        sha256 = (Get-FileHash -LiteralPath $_ -Algorithm SHA256).Hash
    }
})

$manifest = [ordered]@{
    schemaVersion = 1
    runId = $run.runId
    hostBuildCommit = $run.hostBuildCommit
    verificationScriptCommit = $run.verificationScriptCommit
    sourceArtifacts = $sourceArtifacts
}
$manifestPath = Join-Path $packageRoot ("v02-return-manifest-{0}.json" -f $run.verificationScriptCommit.Substring(0, 12))
$manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $manifestPath -Encoding UTF8
$archive = Join-Path $packageRoot ("v02-windows-evidence-{0}-{1}.zip" -f $run.verificationScriptCommit.Substring(0, 12), (Get-Date -Format 'yyyyMMddTHHmmssZ'))
Compress-Archive -Path @($RunDirectory, $manifestPath) -DestinationPath $archive -CompressionLevel Optimal
$archiveHash = ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash).ToLowerInvariant()

$summary = [ordered]@{
    schemaVersion = 1
    spike = 'V-02'
    finalStatusCandidate = $candidate.candidateStatus
    sanitization = [ordered]@{
        contains = @('capability status', 'fake context ID', 'version strings', 'commit IDs', 'SHA-256', 'diagnostic categories')
        excluded = @('absolute paths', 'Windows account names', 'process IDs', 'temporary token values', 'Authorization headers', 'raw log bodies', 'screenshots and recordings')
        rawArchiveCommitted = $false
    }
    targetEnvironment = [ordered]@{
        windows = $environment.actual.windows
        tools = [ordered]@{
            go = $environment.actual.go.version
            python = [ordered]@{
                version = $environment.actual.python.version
                processBits = $pythonProcessBits
            }
            wails = $environment.actual.wails.version
            webview2 = $environment.actual.webview2.version
        }
    }
    build = [ordered]@{
        implementationCommit = $run.hostBuildCommit
        verificationScriptCommit = $run.verificationScriptCommit
        hostBinarySha256 = $run.hostBinarySha256
        coreSourceSha256 = $run.coreSourceSha256
        buildReportHostBinarySha256 = $build.hostBinarySha256
        buildReportCoreSourceSha256 = $build.coreSourceSha256
    }
    validation = $candidate
    sourceArtifacts = $sourceArtifacts
    rawEvidenceArchive = [ordered]@{
        fileName = [System.IO.Path]::GetFileName($archive)
        sha256 = $archiveHash
        controlledLocation = 'Windows working copy under spikes/localhost-core-transport/.evidence/packages; absolute path omitted.'
        accessProcedure = 'Return the archive through the agreed private channel, then verify this SHA-256 before review.'
        retention = 'Retain until Issue #17 and its Draft PR have completed review; do not commit the raw archive or publish it.'
    }
}
$summaryPath = Join-Path $packageRoot ("v02-evidence-summary-{0}.json" -f $run.verificationScriptCommit.Substring(0, 12))
$summary | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $summaryPath -Encoding UTF8

Write-Host "Sanitized summary: $summaryPath"
Write-Host "Raw evidence archive SHA-256: $archiveHash"
Write-Host "Return the summary and archive through the agreed private channel."
