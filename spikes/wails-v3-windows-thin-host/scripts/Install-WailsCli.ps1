[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$versions = Get-Content (Join-Path $root 'versions.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$expected = $versions.candidates.wails.version

$go = Get-Command go -ErrorAction Stop
$actualGo = (& $go.Source version).Trim()
if ($actualGo -notmatch 'go1\.25\.0') {
    throw "需要 Go 1.25.0；当前为 $actualGo。请先安装 $($versions.candidates.go.windowsInstaller)"
}

& $go.Source install 'github.com/wailsapp/wails/v3/cmd/wails3@v3.0.0-beta.8'
if ($LASTEXITCODE -ne 0) {
    throw 'wails3 安装失败。请保留上述输出。'
}

$goPath = (& $go.Source env GOPATH).Trim()
$wails = Join-Path -Path $goPath -ChildPath 'bin\wails3.exe'
if (-not (Test-Path $wails)) {
    throw "未找到刚安装的 wails3：$wails"
}
$actual = (& $wails version 2>&1 | Out-String).Trim()
if ($LASTEXITCODE -ne 0) {
    throw "wails3 version 失败，退出码：$LASTEXITCODE"
}
if ([string]::IsNullOrWhiteSpace($actual)) {
    throw 'wails3 version 没有返回版本文本；请保留上述输出。'
}
if ($actual -notmatch [regex]::Escape($expected)) {
    throw "wails3 版本不符：期望 $expected，实际 $actual"
}
Write-Host "已安装并锁定 wails3 $actual：$wails"
