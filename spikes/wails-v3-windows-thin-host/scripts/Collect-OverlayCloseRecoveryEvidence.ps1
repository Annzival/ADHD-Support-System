[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$configPath = Join-Path $root '.spike-run.json'
if (-not (Test-Path -LiteralPath $configPath)) {
    throw '未找到运行配置；先运行 Start-Spike.ps1 和 Invoke-OverlayCloseRecovery.ps1。'
}

$config = Get-Content -LiteralPath $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
$runDir = [string]$config.evidenceDirectory
$runId = Split-Path -Leaf $runDir
$runPath = Join-Path $runDir 'run.json'
$assessmentPath = Join-Path $runDir 'overlay-close-recovery.json'
$hostEventsPath = Join-Path $runDir 'host-events.jsonl'
foreach ($required in @($runPath, $assessmentPath, $hostEventsPath)) {
    if (-not (Test-Path -LiteralPath $required)) {
        throw "缺少必需的 V-01R 证据文件：$required"
    }
}

$run = Get-Content -LiteralPath $runPath -Raw -Encoding UTF8 | ConvertFrom-Json
$assessment = Get-Content -LiteralPath $assessmentPath -Raw -Encoding UTF8 | ConvertFrom-Json
$buildMarkerPath = Join-Path $root '.spike-build.json'
if (-not (Test-Path -LiteralPath $buildMarkerPath)) {
    throw '未找到构建标记；不能建立二进制身份链。'
}
$buildMarker = Get-Content -LiteralPath $buildMarkerPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($run.hostBuildCommit -ne $buildMarker.buildCommit -or $run.hostBinarySha256 -ne $buildMarker.binarySha256) {
    throw '运行记录与当前构建标记不一致；不能建立二进制身份链。'
}

$preparationRoot = Join-Path $root '.evidence\preparation'
$environmentReport = @(
    Get-ChildItem -LiteralPath $preparationRoot -Filter 'environment-*.json' -File |
        Sort-Object LastWriteTime |
        Select-Object -Last 1
)
if ($environmentReport.Count -ne 1) {
    throw '未找到 Windows 环境报告；先运行 Check-WindowsEnvironment.ps1。'
}
$environment = Get-Content -LiteralPath $environmentReport[0].FullName -Raw -Encoding UTF8 | ConvertFrom-Json

$packageRoot = Join-Path $root '.evidence\packages'
New-Item -ItemType Directory -Force -Path $packageRoot | Out-Null
$verificationCommit = (& git -C $root rev-parse HEAD).Trim()
$rawManifest = [ordered]@{
    generatedAt = (Get-Date).ToUniversalTime().ToString('o')
    spike = 'V-01R'
    runId = $runId
    verificationCommit = $verificationCommit
    hostBuildCommit = $run.hostBuildCommit
    note = '该清单和原始 ZIP 可能包含本机路径或日志正文，只能经受控私有渠道回传，不提交 Git。'
}
$rawManifestPath = Join-Path $packageRoot 'v01r-return-manifest.json'
$rawManifest | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $rawManifestPath -Encoding UTF8

$rawPaths = @($runDir, $environmentReport[0].FullName, $rawManifestPath)
if ($buildMarker.buildReport -and (Test-Path -LiteralPath $buildMarker.buildReport)) {
    $rawPaths += $buildMarker.buildReport
}
$archiveName = "v01r-windows-overlay-close-recovery-{0}-{1}.zip" -f $verificationCommit.Substring(0, 12), (Get-Date -Format 'yyyyMMddTHHmmssZ')
$archivePath = Join-Path $packageRoot $archiveName
Compress-Archive -LiteralPath $rawPaths -DestinationPath $archivePath -CompressionLevel Optimal
$archiveSha256 = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()

$sourceArtifacts = @()
function Add-SourceArtifact {
    param(
        [string]$ID,
        [string]$Path,
        [string]$LogicalName
    )

    if (Test-Path -LiteralPath $Path) {
        $script:sourceArtifacts += [ordered]@{
            id = $ID
            fileName = $LogicalName
            sha256 = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
        }
    }
}

Add-SourceArtifact -ID 'run-metadata' -Path $runPath -LogicalName "$runId/run.json"
Add-SourceArtifact -ID 'host-events' -Path $hostEventsPath -LogicalName "$runId/host-events.jsonl"
Add-SourceArtifact -ID 'overlay-close-recovery' -Path $assessmentPath -LogicalName "$runId/overlay-close-recovery.json"
Add-SourceArtifact -ID 'environment' -Path $environmentReport[0].FullName -LogicalName ("preparation/" + $environmentReport[0].Name)
if ($buildMarker.buildReport) {
    Add-SourceArtifact -ID 'build-report' -Path $buildMarker.buildReport -LogicalName ("preparation/" + [System.IO.Path]::GetFileName($buildMarker.buildReport))
}

$summary = [ordered]@{
    schemaVersion = 1
    spike = 'V-01R'
    finalStatusCandidate = $assessment.overallStatus
    sanitization = [ordered]@{
        contains = @('能力状态', '逐轮观察', '运行标识', '提交标识', '版本', 'SHA-256', '事件种类和进程数量')
        excluded = @('absolute paths', 'Windows account names', 'process IDs', 'raw log bodies', 'screenshots and recordings')
        rawArchiveCommitted = $false
    }
    targetEnvironment = [ordered]@{
        windows = [ordered]@{
            caption = $environment.actual.windows.caption
            version = $environment.actual.windows.version
            buildNumber = $environment.actual.windows.buildNumber
            displayVersion = $environment.actual.windows.displayVersion
            ubr = $environment.actual.windows.ubr
            architecture = if ($environment.actual.windows.is64BitOperatingSystem) { 'x64' } else { 'not-x64' }
        }
        tools = [ordered]@{
            go = $environment.actual.go.version
            python = $environment.actual.python.version
            wails = $environment.actual.wails.version
            webview2 = $environment.actual.webview2.version
        }
    }
    build = [ordered]@{
        implementationCommit = $run.hostBuildCommit
        verificationScriptCommit = $assessment.verificationCommit
        collectionCommit = $verificationCommit
        hostBinarySha256 = $run.hostBinarySha256
    }
    validation = [ordered]@{
        runId = $runId
        rounds = $assessment.rounds
        trayHideShowAfterRounds = $assessment.trayHideShowAfterRounds
        candidateStatus = $assessment.overallStatus
    }
    sourceArtifacts = $sourceArtifacts
    rawEvidenceArchive = [ordered]@{
        fileName = $archiveName
        sha256 = $archiveSha256
        controlledLocation = '证据提供者 Windows 工作副本的 spikes/wails-v3-windows-thin-host/.evidence/packages/；绝对路径不写入摘要。'
        accessProcedure = '审查者在 Issue #14 或对应 Draft PR 请求原件；证据提供者通过本技术 session 或仓库所有者指定的私有传输方式提供，再以此 SHA-256 校验。'
        retention = '证据提供者应至少保留至 Issue #14 的 Draft PR 复审完成且 V-01R 结论已记录；原始 ZIP 不提交 Git 或公开对象存储。'
    }
}
$summaryName = "v01r-overlay-close-recovery-summary-{0}.json" -f $verificationCommit.Substring(0, 12)
$summaryPath = Join-Path $packageRoot $summaryName
[System.IO.File]::WriteAllText(
    $summaryPath,
    ($summary | ConvertTo-Json -Depth 12),
    [System.Text.UTF8Encoding]::new($false)
)

Write-Host "请回传原始证据 ZIP：$archivePath"
Write-Host "ZIP SHA-256：$archiveSha256"
Write-Host "请同时回传脱敏机器可读摘要：$summaryPath"
