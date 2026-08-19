[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$versions = Get-Content -LiteralPath (Join-Path $root 'versions.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$go = Get-Command go -ErrorAction Stop
$actualGo = (& $go.Source version).Trim()
if ($actualGo -notmatch 'go1\.25\.0') {
    throw "Expected Go 1.25.0; found $actualGo. Install $($versions.candidates.go.windowsInstaller)."
}

& $go.Source install 'github.com/wailsapp/wails/v3/cmd/wails3@v3.0.0-beta.8'
if ($LASTEXITCODE -ne 0) {
    throw 'Pinned Wails CLI installation failed.'
}

$goPath = (& $go.Source env GOPATH).Trim()
$wails = Join-Path -Path $goPath -ChildPath 'bin\wails3.exe'
if (-not (Test-Path -LiteralPath $wails)) {
    throw "Pinned Wails CLI was not found at $wails."
}

$process = New-Object System.Diagnostics.Process
$process.StartInfo.FileName = $wails
$process.StartInfo.Arguments = 'version'
$process.StartInfo.UseShellExecute = $false
$process.StartInfo.RedirectStandardOutput = $true
$process.StartInfo.RedirectStandardError = $true
[void]$process.Start()
$standardOutput = $process.StandardOutput.ReadToEnd()
$standardError = $process.StandardError.ReadToEnd()
$process.WaitForExit()
$actual = @($standardOutput, $standardError) -join [Environment]::NewLine
$actual = $actual.Trim()
if ($process.ExitCode -ne 0 -or [string]::IsNullOrWhiteSpace($actual)) {
    throw "Pinned Wails CLI version check failed with exit code $($process.ExitCode)."
}
if ($actual -notmatch [regex]::Escape($versions.candidates.wails.version)) {
    throw "Expected Wails $($versions.candidates.wails.version); found $actual."
}

Write-Host "Pinned Wails CLI ready: $actual"
