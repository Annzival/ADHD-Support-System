[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
& (Join-Path $PSScriptRoot 'Check-WindowsEnvironment.ps1')
if ($LASTEXITCODE -ne 0) { throw '环境检查未通过；未开始构建。' }

$go = (Get-Command go -ErrorAction Stop).Source
$pythonExe = (& py -3.12 -c 'import sys; print(sys.executable)').Trim()
$binary = Join-Path $root 'bin\wails-v3-windows-thin-host.exe'
$buildCommit = (& git -C $root rev-parse HEAD).Trim()
$evidence = Join-Path $root '.evidence\preparation'
New-Item -ItemType Directory -Force -Path $evidence | Out-Null
$logPath = Join-Path $evidence ("build-{0}.log" -f (Get-Date -Format 'yyyyMMddTHHmmssZ'))

function Invoke-NativeBuildCommand {
    param(
        [string]$FileName,
        [string]$Arguments,
        [string]$Description
    )

    $process = New-Object System.Diagnostics.Process
    $process.StartInfo.FileName = $FileName
    $process.StartInfo.Arguments = $Arguments
    $process.StartInfo.WorkingDirectory = $root
    $process.StartInfo.UseShellExecute = $false
    $process.StartInfo.RedirectStandardOutput = $true
    $process.StartInfo.RedirectStandardError = $true
    [void]$process.Start()
    $standardOutputTask = $process.StandardOutput.ReadToEndAsync()
    $standardErrorTask = $process.StandardError.ReadToEndAsync()
    $process.WaitForExit()
    [System.Threading.Tasks.Task]::WaitAll(@($standardOutputTask, $standardErrorTask))
    $output = "$($standardOutputTask.Result)$($standardErrorTask.Result)"
    if (-not [string]::IsNullOrWhiteSpace($output)) {
        $output | Tee-Object -FilePath $logPath -Append
    }
    if ($process.ExitCode -ne 0) {
        throw "$Description 失败，退出码：$($process.ExitCode)。"
    }
}

Push-Location $root
try {
    Invoke-NativeBuildCommand -FileName $go -Arguments 'mod download' -Description 'go mod download'
    Invoke-NativeBuildCommand -FileName $go -Arguments 'test ./...' -Description 'go test'
    Invoke-NativeBuildCommand -FileName $pythonExe -Arguments '-m unittest discover -s agent_core -p test_*.py' -Description 'Python 测试替身检查'
    New-Item -ItemType Directory -Force -Path (Split-Path $binary) | Out-Null
    Invoke-NativeBuildCommand -FileName $go -Arguments ("build -buildvcs=false -o `"$binary`" .") -Description 'Windows Wails 宿主构建'
} finally {
    Pop-Location
}

$report = [ordered]@{
    generatedAt = (Get-Date).ToUniversalTime().ToString('o')
    buildCommit = $buildCommit
    binary = $binary
    binarySha256 = (Get-FileHash $binary -Algorithm SHA256).Hash
    log = $logPath
    goVersion = (& $go version).Trim()
    pythonVersion = (& $pythonExe --version).Trim()
}
$reportPath = Join-Path $evidence ("build-{0}.json" -f (Get-Date -Format 'yyyyMMddTHHmmssZ'))
$report | ConvertTo-Json -Depth 6 | Set-Content -Path $reportPath -Encoding UTF8
$buildMarker = [ordered]@{
    buildCommit = $buildCommit
    binary = $binary
    binarySha256 = $report.binarySha256
    buildReport = $reportPath
}
[System.IO.File]::WriteAllText((Join-Path $root '.spike-build.json'), ($buildMarker | ConvertTo-Json -Depth 5), [System.Text.UTF8Encoding]::new($false))
Write-Host "构建成功：$binary"
Write-Host "构建报告：$reportPath"
