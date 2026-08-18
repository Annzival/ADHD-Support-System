[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
& (Join-Path $PSScriptRoot 'Check-WindowsEnvironment.ps1')
if ($LASTEXITCODE -ne 0) {
    throw 'Environment validation failed; build was not started.'
}

$go = (Get-Command go -ErrorAction Stop).Source
$pythonExecutable = (& py -3.12 -c 'import sys; print(sys.executable)').Trim()
$evidence = Join-Path $root '.evidence\preparation'
$binary = Join-Path $root 'bin\localhost-core-transport.exe'
$buildCommit = (& git -C $root rev-parse HEAD).Trim()
$logPath = Join-Path $evidence ("build-{0}.log" -f (Get-Date -Format 'yyyyMMddTHHmmssZ'))

function Invoke-NativeBuildCommand {
    param([string]$FileName, [string]$Arguments, [string]$Description)
    $process = New-Object System.Diagnostics.Process
    $process.StartInfo.FileName = $FileName
    $process.StartInfo.Arguments = $Arguments
    $process.StartInfo.WorkingDirectory = $root
    $process.StartInfo.UseShellExecute = $false
    $process.StartInfo.RedirectStandardOutput = $true
    $process.StartInfo.RedirectStandardError = $true
    [void]$process.Start()
    $stdoutTask = $process.StandardOutput.ReadToEndAsync()
    $stderrTask = $process.StandardError.ReadToEndAsync()
    $process.WaitForExit()
    [System.Threading.Tasks.Task]::WaitAll(@($stdoutTask, $stderrTask))
    $output = "$($stdoutTask.Result)$($stderrTask.Result)"
    if (-not [string]::IsNullOrWhiteSpace($output)) {
        $output | Tee-Object -FilePath $logPath -Append
    }
    if ($process.ExitCode -ne 0) {
        throw "$Description failed with exit code $($process.ExitCode)."
    }
}

Invoke-NativeBuildCommand -FileName $go -Arguments 'mod download' -Description 'go mod download'
Invoke-NativeBuildCommand -FileName $go -Arguments 'test ./...' -Description 'go test'
Invoke-NativeBuildCommand -FileName $pythonExecutable -Arguments '-m unittest discover -s agent_core -p test_*.py' -Description 'Python Core tests'
$staticReport = ".evidence\preparation\static-contract-$($buildCommit.Substring(0, 12)).json"
$quote = [char]34
Invoke-NativeBuildCommand -FileName $pythonExecutable -Arguments "scripts\verify_static_contract.py --report-path $($quote)$staticReport$($quote)" -Description 'static contract check'
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $binary) | Out-Null
Invoke-NativeBuildCommand -FileName $go -Arguments "build -buildvcs=false -o $($quote)$binary$($quote) ." -Description 'Wails host build'

$report = [ordered]@{
    generatedAt = (Get-Date).ToUniversalTime().ToString('o')
    buildCommit = $buildCommit
    hostBinarySha256 = (Get-FileHash -LiteralPath $binary -Algorithm SHA256).Hash
    coreSourceSha256 = (Get-FileHash -LiteralPath (Join-Path $root 'agent_core\agent_core_stub.py') -Algorithm SHA256).Hash
    goVersion = (& $go version).Trim()
    pythonVersion = (& $pythonExecutable --version).Trim()
}
$reportPath = Join-Path $evidence ("build-{0}.json" -f (Get-Date -Format 'yyyyMMddTHHmmssZ'))
$report | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $reportPath -Encoding UTF8
$marker = [ordered]@{
    buildCommit = $buildCommit
    hostBinarySha256 = $report.hostBinarySha256
    coreSourceSha256 = $report.coreSourceSha256
    buildReportFile = [System.IO.Path]::GetFileName($reportPath)
}
[System.IO.File]::WriteAllText((Join-Path $root '.spike-build.json'), ($marker | ConvertTo-Json -Depth 5), [System.Text.UTF8Encoding]::new($false))
Write-Host "Build complete: $binary"
Write-Host "Build report: $reportPath"
