[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
& (Join-Path $PSScriptRoot 'Check-WindowsEnvironment.ps1')
if ($LASTEXITCODE -ne 0) { throw '环境检查未通过；未开始构建。' }

$go = (Get-Command go -ErrorAction Stop).Source
$pythonExe = (& py -3.12 -c 'import sys; print(sys.executable)').Trim()
$binary = Join-Path $root 'bin\wails-v3-windows-thin-host.exe'
$evidence = Join-Path $root '.evidence\preparation'
New-Item -ItemType Directory -Force -Path $evidence | Out-Null
$logPath = Join-Path $evidence ("build-{0}.log" -f (Get-Date -Format 'yyyyMMddTHHmmssZ'))

Push-Location $root
try {
    & $go mod download 2>&1 | Tee-Object -FilePath $logPath
    if ($LASTEXITCODE -ne 0) { throw 'go mod download 失败。' }
    & $go test ./... 2>&1 | Tee-Object -FilePath $logPath -Append
    if ($LASTEXITCODE -ne 0) { throw 'go test 失败。' }
    & $pythonExe -m unittest discover -s agent_core -p 'test_*.py' 2>&1 | Tee-Object -FilePath $logPath -Append
    if ($LASTEXITCODE -ne 0) { throw 'Python 测试替身检查失败。' }
    New-Item -ItemType Directory -Force -Path (Split-Path $binary) | Out-Null
    & $go build -buildvcs=false -o $binary . 2>&1 | Tee-Object -FilePath $logPath -Append
    if ($LASTEXITCODE -ne 0) { throw 'Windows Wails 宿主构建失败。' }
} finally {
    Pop-Location
}

$report = [ordered]@{
    generatedAt = (Get-Date).ToUniversalTime().ToString('o')
    binary = $binary
    binarySha256 = (Get-FileHash $binary -Algorithm SHA256).Hash
    log = $logPath
    goVersion = (& $go version).Trim()
    pythonVersion = (& $pythonExe --version).Trim()
}
$reportPath = Join-Path $evidence ("build-{0}.json" -f (Get-Date -Format 'yyyyMMddTHHmmssZ'))
$report | ConvertTo-Json -Depth 6 | Set-Content -Path $reportPath -Encoding UTF8
Write-Host "构建成功：$binary"
Write-Host "构建报告：$reportPath"
