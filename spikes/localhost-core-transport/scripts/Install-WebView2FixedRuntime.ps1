[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$versions = Get-Content -LiteralPath (Join-Path $root 'versions.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$candidate = $versions.candidates.webview2
$tools = Join-Path $root '.tools'
$destination = Join-Path $tools "webview2-fixed-$($candidate.version)-$($candidate.architecture)"
$cab = Join-Path $tools "Microsoft.WebView2.FixedVersionRuntime.$($candidate.version).$($candidate.architecture).cab"

New-Item -ItemType Directory -Force -Path $tools | Out-Null
if (-not (Get-ChildItem -Path $destination -Filter 'msedgewebview2.exe' -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1)) {
    if (-not (Test-Path -LiteralPath $cab)) {
        Invoke-WebRequest -Uri $candidate.cabUrl -OutFile $cab
    }
    New-Item -ItemType Directory -Force -Path $destination | Out-Null
    & "$env:WINDIR\System32\expand.exe" $cab '-F:*' $destination
    if ($LASTEXITCODE -ne 0) {
        throw 'Fixed Version WebView2 extraction failed.'
    }
}

$browser = Get-ChildItem -Path $destination -Filter 'msedgewebview2.exe' -Recurse | Select-Object -First 1
if (-not $browser) {
    throw 'Fixed Version WebView2 executable was not found.'
}
if ($browser.VersionInfo.FileVersion -notmatch [regex]::Escape($candidate.version)) {
    throw "Expected WebView2 $($candidate.version); found $($browser.VersionInfo.FileVersion)."
}

& icacls $destination '/grant' '*S-1-15-2-2:(OI)(CI)(RX)' '/grant' '*S-1-15-2-1:(OI)(CI)(RX)' | Out-Host
if ($LASTEXITCODE -ne 0) {
    throw 'Could not grant Fixed Version WebView2 AppContainer read access.'
}

Write-Host "Fixed Version WebView2 ready: $($browser.DirectoryName)"
