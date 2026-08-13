[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$verificationCommit = (& git -C $root rev-parse HEAD).Trim()
$configPath = Join-Path $root '.spike-run.json'
if (-not (Test-Path $configPath)) { throw '未找到运行配置；无法确定要收集的证据运行。' }
$runDir = (Get-Content $configPath -Raw -Encoding UTF8 | ConvertFrom-Json).evidenceDirectory
$runFile = Join-Path $runDir 'run.json'
if (-not (Test-Path $runFile)) { throw "当前运行目录缺少 run.json：$runDir" }
$selected = @(Get-Item -LiteralPath $runDir)
$hostBuildCommit = (Get-Content $runFile -Raw -Encoding UTF8 | ConvertFrom-Json).commit

$packageRoot = Join-Path $root '.evidence\packages'
New-Item -ItemType Directory -Force -Path $packageRoot | Out-Null
$manifest = [ordered]@{
    generatedAt = (Get-Date).ToUniversalTime().ToString('o')
    hostBuildCommit = $hostBuildCommit
    verificationCommit = $verificationCommit
    runs = @($selected.FullName)
    screenshotsOrVideos = '请与 ZIP 一起单独回传；不要把可能含私人桌面内容的大型录像提交到仓库。'
}
$manifestPath = Join-Path $packageRoot 'return-manifest.json'
$manifest | ConvertTo-Json -Depth 6 | Set-Content -Path $manifestPath -Encoding UTF8
$zip = Join-Path $packageRoot ("v01-windows-evidence-{0}-{1}-{2}.zip" -f $hostBuildCommit.Substring(0, 12), $verificationCommit.Substring(0, 12), (Get-Date -Format 'yyyyMMddTHHmmssZ'))
$paths = @($selected.FullName) + @($manifestPath)
Compress-Archive -Path $paths -DestinationPath $zip -CompressionLevel Optimal
Write-Host "请回传此 ZIP：$zip"
Write-Host '并单独附上人工观察中填写的截图/录屏（如有）。'
