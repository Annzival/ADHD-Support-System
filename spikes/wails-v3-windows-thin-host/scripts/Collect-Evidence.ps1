[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$commit = (& git -C $root rev-parse HEAD).Trim()
$runsRoot = Join-Path $root '.evidence\runs'
if (-not (Test-Path $runsRoot)) { throw '没有可收集的运行证据。' }

$selected = Get-ChildItem -Path $runsRoot -Directory | Where-Object {
    $runFile = Join-Path $_.FullName 'run.json'
    (Test-Path $runFile) -and ((Get-Content $runFile -Raw | ConvertFrom-Json).commit -eq $commit)
}
if ($selected.Count -eq 0) { throw "没有当前 commit $commit 的运行证据。" }

$packageRoot = Join-Path $root '.evidence\packages'
New-Item -ItemType Directory -Force -Path $packageRoot | Out-Null
$manifest = [ordered]@{
    generatedAt = (Get-Date).ToUniversalTime().ToString('o')
    commit = $commit
    runs = @($selected.FullName)
    screenshotsOrVideos = '请与 ZIP 一起单独回传；不要把可能含私人桌面内容的大型录像提交到仓库。'
}
$manifestPath = Join-Path $packageRoot 'return-manifest.json'
$manifest | ConvertTo-Json -Depth 6 | Set-Content -Path $manifestPath -Encoding UTF8
$zip = Join-Path $packageRoot ("v01-windows-evidence-{0}-{1}.zip" -f $commit.Substring(0, 12), (Get-Date -Format 'yyyyMMddTHHmmssZ'))
$paths = @($selected.FullName) + @($manifestPath)
Compress-Archive -Path $paths -DestinationPath $zip -CompressionLevel Optimal
Write-Host "请回传此 ZIP：$zip"
Write-Host '并单独附上人工观察中填写的截图/录屏（如有）。'
