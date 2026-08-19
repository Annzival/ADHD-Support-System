[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$binary = Join-Path $root 'bin\localhost-core-transport.exe'
$markerPath = Join-Path $root '.spike-build.json'
if (-not (Test-Path -LiteralPath $binary) -or -not (Test-Path -LiteralPath $markerPath)) {
    throw 'Build marker or host binary is missing. Run Build-Spike.ps1 first.'
}

$marker = Get-Content -LiteralPath $markerPath -Raw -Encoding UTF8 | ConvertFrom-Json
$actualHostHash = (Get-FileHash -LiteralPath $binary -Algorithm SHA256).Hash
if ($marker.hostBinarySha256 -ne $actualHostHash -or [string]::IsNullOrWhiteSpace($marker.buildCommit)) {
    throw 'Build marker does not match the host binary.'
}
& (Join-Path $PSScriptRoot 'Check-WindowsEnvironment.ps1')
if ($LASTEXITCODE -ne 0) {
    throw 'Environment validation failed; host was not started.'
}

$processName = [System.IO.Path]::GetFileNameWithoutExtension($binary)
if (@(Get-Process -Name $processName -ErrorAction SilentlyContinue).Count -gt 0) {
    throw 'A V-02 host process is already running. Run Cleanup-Spike.ps1 before starting another evidence run.'
}

$versions = Get-Content -LiteralPath (Join-Path $root 'versions.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$runtimeRoot = Join-Path $root ".tools\webview2-fixed-$($versions.candidates.webview2.version)-$($versions.candidates.webview2.architecture)"
$browser = Get-ChildItem -Path $runtimeRoot -Filter 'msedgewebview2.exe' -Recurse | Select-Object -First 1
if (-not $browser) {
    throw 'Fixed Version WebView2 is unavailable.'
}

$pythonExecutable = (& py -3.12 -c 'import sys; print(sys.executable)').Trim()
$verificationCommit = (& git -C $root rev-parse HEAD).Trim()
$runId = "run-{0}-{1}" -f (Get-Date -Format 'yyyyMMddTHHmmssZ'), $verificationCommit.Substring(0, 12)
$runDirectory = Join-Path $root ".evidence\runs\$runId"
New-Item -ItemType Directory -Force -Path $runDirectory | Out-Null

$config = [ordered]@{
    pythonExecutable = $pythonExecutable
    webView2BrowserPath = $browser.DirectoryName
    evidenceDirectory = $runDirectory
    handshakeTimeoutMs = 900
}
[System.IO.File]::WriteAllText((Join-Path $root '.spike-run.json'), ($config | ConvertTo-Json -Depth 5), [System.Text.UTF8Encoding]::new($false))
$run = [ordered]@{
    runId = $runId
    startedAt = (Get-Date).ToUniversalTime().ToString('o')
    hostBuildCommit = $marker.buildCommit
    verificationScriptCommit = $verificationCommit
    hostBinarySha256 = $actualHostHash
    coreSourceSha256 = $marker.coreSourceSha256
    target = [ordered]@{
        windows = 'Windows 10 22H2 x64'
        wails = $versions.candidates.wails.version
        python = $versions.candidates.python.version
        webview2 = $versions.candidates.webview2.version
    }
}
$run | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $runDirectory 'run.json') -Encoding UTF8

$process = Start-Process -FilePath $binary -WorkingDirectory $root -PassThru -Wait -RedirectStandardOutput (Join-Path $runDirectory 'host-stdout.log') -RedirectStandardError (Join-Path $runDirectory 'host-stderr.log')
if ($process.ExitCode -ne 0) {
    throw "Wails host exited with code $($process.ExitCode). Preserve $runDirectory."
}
& (Join-Path $PSScriptRoot 'Test-ValidationEvidence.ps1') -RunDirectory $runDirectory
if ($LASTEXITCODE -ne 0) {
    throw "Candidate evidence was not accepted. Preserve $runDirectory."
}

Write-Host "Evidence run complete: $runDirectory"
