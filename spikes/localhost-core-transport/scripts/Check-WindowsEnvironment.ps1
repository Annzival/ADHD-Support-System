[CmdletBinding()]
param()

$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $PSScriptRoot
$versions = Get-Content -LiteralPath (Join-Path $root 'versions.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$evidence = Join-Path $root '.evidence\preparation'
New-Item -ItemType Directory -Force -Path $evidence | Out-Null

$report = [ordered]@{
    generatedAt = (Get-Date).ToUniversalTime().ToString('o')
    actual = [ordered]@{}
    checks = [ordered]@{}
    errors = @()
}

function Add-Check {
    param([string]$Name, [bool]$Passed, [string]$Detail)
    $report.checks[$Name] = [ordered]@{ passed = $Passed; detail = $Detail }
    if (-not $Passed) {
        $script:report.errors += "${Name}: $Detail"
    }
}

function Invoke-CapturedNative {
    param([string]$FileName, [string]$Arguments)
    $process = New-Object System.Diagnostics.Process
    $process.StartInfo.FileName = $FileName
    $process.StartInfo.Arguments = $Arguments
    $process.StartInfo.UseShellExecute = $false
    $process.StartInfo.RedirectStandardOutput = $true
    $process.StartInfo.RedirectStandardError = $true
    [void]$process.Start()
    $stdout = $process.StandardOutput.ReadToEnd()
    $stderr = $process.StandardError.ReadToEnd()
    $process.WaitForExit()
    return [ordered]@{
        exitCode = $process.ExitCode
        output = (@($stdout, $stderr) -join [Environment]::NewLine).Trim()
    }
}

$os = Get-CimInstance Win32_OperatingSystem
$currentVersion = Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion'
$report.actual.windows = [ordered]@{
    caption = $os.Caption
    version = $os.Version
    buildNumber = $os.BuildNumber
    displayVersion = $currentVersion.DisplayVersion
    ubr = $currentVersion.UBR
    is64BitOperatingSystem = [Environment]::Is64BitOperatingSystem
}
$windowsPassed = $report.actual.windows.displayVersion -eq $versions.candidates.windows.release -and $report.actual.windows.buildNumber -eq $versions.candidates.windows.baseBuild -and $report.actual.windows.is64BitOperatingSystem
Add-Check 'windows_10_22h2_x64' $windowsPassed ($report.actual.windows | ConvertTo-Json -Compress)

$go = Get-Command go -ErrorAction SilentlyContinue
if ($go) {
    $goVersion = (& $go.Source version).Trim()
    $report.actual.go = [ordered]@{ version = $goVersion }
    Add-Check 'go_1_25_0' ($goVersion -match 'go1\.25\.0') $goVersion
} else {
    Add-Check 'go_1_25_0' $false 'go command not found'
}

$py = Get-Command py -ErrorAction SilentlyContinue
if ($py) {
    $pythonVersion = (& $py.Source '-3.12' '--version' 2>&1 | Out-String).Trim()
    $pythonExecutable = (& $py.Source '-3.12' '-c' 'import sys; print(sys.executable)').Trim()
    $report.actual.python = [ordered]@{ version = $pythonVersion; executable = $pythonExecutable }
    Add-Check 'python_3_12_3_x64' ($pythonVersion -match '3\.12\.3') $pythonVersion
} else {
    Add-Check 'python_3_12_3_x64' $false 'py launcher not found'
}

if ($go) {
    $goPath = (& $go.Source env GOPATH).Trim()
    $wails = Join-Path -Path $goPath -ChildPath 'bin\wails3.exe'
    if (Test-Path -LiteralPath $wails) {
        $wailsVersion = Invoke-CapturedNative -FileName $wails -Arguments 'version'
        $report.actual.wails = [ordered]@{ version = $wailsVersion.output; exitCode = $wailsVersion.exitCode }
        Add-Check 'wails_v3_beta_8' ($wailsVersion.exitCode -eq 0 -and $wailsVersion.output -match [regex]::Escape($versions.candidates.wails.version)) $wailsVersion.output
    } else {
        Add-Check 'wails_v3_beta_8' $false 'wails3.exe not found'
    }
} else {
    Add-Check 'wails_v3_beta_8' $false 'Go is required to locate wails3.exe'
}

$runtimeRoot = Join-Path $root ".tools\webview2-fixed-$($versions.candidates.webview2.version)-$($versions.candidates.webview2.architecture)"
$browser = Get-ChildItem -Path $runtimeRoot -Filter 'msedgewebview2.exe' -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
if ($browser) {
    $report.actual.webview2 = [ordered]@{ version = $browser.VersionInfo.FileVersion }
    Add-Check 'webview2_fixed_151_0_4129_78_x64' ($browser.VersionInfo.FileVersion -match [regex]::Escape($versions.candidates.webview2.version)) $browser.VersionInfo.FileVersion
} else {
    Add-Check 'webview2_fixed_151_0_4129_78_x64' $false 'Fixed Version WebView2 executable not found'
}

$path = Join-Path $evidence ("environment-{0}.json" -f (Get-Date -Format 'yyyyMMddTHHmmssZ'))
$report | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $path -Encoding UTF8
Write-Host "Environment report: $path"
if ($report.errors.Count -gt 0) {
    Write-Error ($report.errors -join [Environment]::NewLine)
    exit 1
}
