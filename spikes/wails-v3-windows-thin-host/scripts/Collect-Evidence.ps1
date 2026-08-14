[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$verificationCommit = (& git -C $root rev-parse HEAD).Trim()
$runsRoot = Join-Path $root '.evidence\runs'
if (-not (Test-Path $runsRoot)) { throw '没有可收集的运行证据。' }
$selected = @()
$excludedRuns = @()
foreach ($candidate in @(Get-ChildItem -LiteralPath $runsRoot -Directory | Sort-Object Name)) {
    $runFile = Join-Path $candidate.FullName 'run.json'
    $hostLog = Join-Path $candidate.FullName 'host-events.jsonl'
    $hostStderr = Join-Path $candidate.FullName 'host-stderr.log'
    if (-not (Test-Path $runFile) -or -not (Test-Path $hostLog)) { continue }
    $stderrText = if (Test-Path $hostStderr) { Get-Content $hostStderr -Raw -Encoding UTF8 } else { '' }
    if ($stderrText -match 'read \.spike-run\.json:|parse required \.spike-run\.json:') {
        $excludedRuns += [ordered]@{ path = $candidate.FullName; reason = '宿主未加载 .spike-run.json' }
    } else {
        $selected += $candidate
    }
}
if ($selected.Count -eq 0) { throw '没有配置加载成功且包含宿主事件日志的运行可打包。' }
$hostBuildCommits = @($selected | ForEach-Object {
    $metadata = Get-Content (Join-Path $_.FullName 'run.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($null -ne $metadata.hostBuildCommit) { $metadata.hostBuildCommit } else { $metadata.commit }
} | Sort-Object -Unique)

$packageRoot = Join-Path $root '.evidence\packages'
New-Item -ItemType Directory -Force -Path $packageRoot | Out-Null
$manifest = [ordered]@{
    generatedAt = (Get-Date).ToUniversalTime().ToString('o')
    hostBuildCommits = $hostBuildCommits
    verificationCommit = $verificationCommit
    runs = @($selected.FullName)
    excludedRuns = $excludedRuns
    screenshotsOrVideos = '请与 ZIP 一起单独回传；不要把可能含私人桌面内容的大型录像提交到仓库。'
}
$manifestPath = Join-Path $packageRoot 'return-manifest.json'
$manifest | ConvertTo-Json -Depth 6 | Set-Content -Path $manifestPath -Encoding UTF8
$zip = Join-Path $packageRoot ("v01-windows-evidence-{0}-{1}.zip" -f $verificationCommit.Substring(0, 12), (Get-Date -Format 'yyyyMMddTHHmmssZ'))
$paths = @($selected.FullName) + @($manifestPath)
Compress-Archive -Path $paths -DestinationPath $zip -CompressionLevel Optimal
Write-Host "请回传此 ZIP：$zip"
Write-Host '并单独附上人工观察中填写的截图/录屏（如有）。'
