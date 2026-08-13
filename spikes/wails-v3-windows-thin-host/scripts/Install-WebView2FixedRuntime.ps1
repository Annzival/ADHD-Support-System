[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$versions = Get-Content (Join-Path $root 'versions.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$candidate = $versions.candidates.webview2
$tools = Join-Path $root '.tools'
$destination = Join-Path $tools "webview2-fixed-$($candidate.version)-$($candidate.architecture)"
$cab = Join-Path $tools "Microsoft.WebView2.FixedVersionRuntime.$($candidate.version).$($candidate.architecture).cab"

New-Item -ItemType Directory -Force -Path $tools | Out-Null
if (-not (Get-ChildItem -Path $destination -Filter 'msedgewebview2.exe' -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1)) {
    if (-not (Test-Path $cab)) {
        Write-Host "下载 WebView2 Fixed Version $($candidate.version) x64（文件较大，请保持网络连接）..."
        Invoke-WebRequest -Uri $candidate.cabUrl -OutFile $cab
    }
    New-Item -ItemType Directory -Force -Path $destination | Out-Null
    & "$env:WINDIR\System32\expand.exe" $cab '-F:*' $destination
    if ($LASTEXITCODE -ne 0) {
        throw '解压 WebView2 Fixed Version CAB 失败。'
    }
}

$browser = Get-ChildItem -Path $destination -Filter 'msedgewebview2.exe' -Recurse | Select-Object -First 1
if (-not $browser) {
    throw "在 $destination 未找到 msedgewebview2.exe"
}
$actual = $browser.VersionInfo.FileVersion
if ($actual -notmatch [regex]::Escape($candidate.version)) {
    throw "WebView2 版本不符：期望 $($candidate.version)，实际 $actual"
}

# Fixed Version Runtime on Windows 10 needs AppContainer read/execute rights.
& icacls $destination '/grant' '*S-1-15-2-2:(OI)(CI)(RX)' '/grant' '*S-1-15-2-1:(OI)(CI)(RX)' | Out-Host
if ($LASTEXITCODE -ne 0) {
    throw '无法为 WebView2 Fixed Version 设置 AppContainer 读取权限。'
}
Write-Host "WebView2 Fixed Version 已就绪：$($browser.DirectoryName)"
