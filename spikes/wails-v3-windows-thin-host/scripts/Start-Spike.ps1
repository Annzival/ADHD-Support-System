[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$binary = Join-Path $root 'bin\wails-v3-windows-thin-host.exe'
if (-not (Test-Path $binary)) { throw '未找到已构建宿主；先运行 .\scripts\Build-Spike.ps1' }
& (Join-Path $PSScriptRoot 'Check-WindowsEnvironment.ps1')
if ($LASTEXITCODE -ne 0) { throw '环境检查未通过；未启动宿主。' }

$hostProcessName = [System.IO.Path]::GetFileNameWithoutExtension($binary)
$existing = @(Get-Process -Name $hostProcessName -ErrorAction SilentlyContinue)
if ($existing.Count -gt 0) {
    throw "验证宿主已在运行（PID: $($existing.Id -join ', ')）。先按清理脚本处理，避免混合证据。"
}

$versions = Get-Content (Join-Path $root 'versions.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$runtimeRoot = Join-Path $root ".tools\webview2-fixed-$($versions.candidates.webview2.version)-$($versions.candidates.webview2.architecture)"
$browser = Get-ChildItem -Path $runtimeRoot -Filter 'msedgewebview2.exe' -Recurse | Select-Object -First 1
$pythonExe = (& py -3.12 -c 'import sys; print(sys.executable)').Trim()
$commit = (& git -C $root rev-parse HEAD).Trim()
$runId = "run-{0}-{1}" -f (Get-Date -Format 'yyyyMMddTHHmmssZ'), $commit.Substring(0, 12)
$runDir = Join-Path $root ".evidence\runs\$runId"
New-Item -ItemType Directory -Force -Path $runDir | Out-Null

$config = [ordered]@{
    pythonExecutable = $pythonExe
    webView2BrowserPath = $browser.DirectoryName
    evidenceDirectory = $runDir
    corePort = 18765
}
$configPath = Join-Path $root '.spike-run.json'
$configJson = $config | ConvertTo-Json -Depth 4
# Windows PowerShell 5.1's Set-Content -Encoding UTF8 emits a BOM. The host
# tolerates that defensively, but this is deliberately BOM-free JSON so its
# on-disk validation configuration is portable to Go and other JSON readers.
[System.IO.File]::WriteAllText($configPath, $configJson, [System.Text.UTF8Encoding]::new($false))

$process = Start-Process -FilePath $binary -WorkingDirectory $root -PassThru -RedirectStandardOutput (Join-Path $runDir 'host-stdout.log') -RedirectStandardError (Join-Path $runDir 'host-stderr.log')
$run = [ordered]@{
    startedAt = (Get-Date).ToUniversalTime().ToString('o')
    commit = $commit
    hostExecutable = $binary
    hostPid = $process.Id
    runConfig = $config
}
$run | ConvertTo-Json -Depth 6 | Set-Content -Path (Join-Path $runDir 'run.json') -Encoding UTF8

$deadline = (Get-Date).AddSeconds(15)
do {
    try {
        $health = Invoke-RestMethod -Uri 'http://127.0.0.1:18765/health' -TimeoutSec 2
        if ($health.status -eq 'ok') { break }
    } catch { Start-Sleep -Milliseconds 300 }
} while ((Get-Date) -lt $deadline)
if ($health.status -ne 'ok') {
    throw "宿主已启动（PID $($process.Id)），但测试替身未在 15 秒内通过健康检查；请保留 $runDir。"
}
Write-Host "验证宿主已启动：PID $($process.Id)"
Write-Host "本次证据目录：$runDir"
