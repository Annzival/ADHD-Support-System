[CmdletBinding()]
param()

$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $PSScriptRoot
$versions = Get-Content (Join-Path $root 'versions.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$evidence = Join-Path $root '.evidence\preparation'
New-Item -ItemType Directory -Force -Path $evidence | Out-Null

$report = [ordered]@{
    generatedAt = (Get-Date).ToUniversalTime().ToString('o')
    expected = $versions.candidates
    actual = [ordered]@{}
    checks = [ordered]@{}
    errors = @()
}

function Add-Check([string]$name, [bool]$passed, [string]$detail) {
    $report.checks[$name] = [ordered]@{ passed = $passed; detail = $detail }
    if (-not $passed) { $script:report.errors += "${name}: $detail" }
}

$os = Get-CimInstance Win32_OperatingSystem
$is64BitOperatingSystem = [Environment]::Is64BitOperatingSystem
$report.actual.windows = [ordered]@{
    caption = $os.Caption
    version = $os.Version
    buildNumber = $os.BuildNumber
    osArchitecture = $os.OSArchitecture
    is64BitOperatingSystem = $is64BitOperatingSystem
    displayVersion = (Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion').DisplayVersion
    ubr = (Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion').UBR
}
$targetWindows = $report.actual.windows.displayVersion -eq '22H2' -and $report.actual.windows.buildNumber -eq '19045' -and $is64BitOperatingSystem
Add-Check 'windows_10_22h2_x64' $targetWindows ("{0}; Version={1}; BuildNumber={2}; OSArchitecture={3}; Is64BitOperatingSystem={4}; DisplayVersion={5}; UBR={6}" -f $os.Caption, $report.actual.windows.version, $report.actual.windows.buildNumber, $report.actual.windows.osArchitecture, $is64BitOperatingSystem, $report.actual.windows.displayVersion, $report.actual.windows.ubr)

$goCommand = Get-Command go -ErrorAction SilentlyContinue
if ($goCommand) {
    $goVersion = (& $goCommand.Source version 2>&1 | Out-String).Trim()
    $report.actual.go = [ordered]@{ command = $goCommand.Source; version = $goVersion }
    Add-Check 'go_1_25_0' ($goVersion -match 'go1\.25\.0') $goVersion
} else {
    Add-Check 'go_1_25_0' $false "未找到 go；安装 $($versions.candidates.go.windowsInstaller) 后重新打开 PowerShell。"
}

$pythonCommand = Get-Command py -ErrorAction SilentlyContinue
if ($pythonCommand) {
    $pythonLines = @(& $pythonCommand.Source '-3.12' '-c' 'import sys; print(sys.executable); print(sys.version)' 2>&1)
    $pythonExe = if ($pythonLines.Count -gt 0) { $pythonLines[0].ToString() } else { '' }
    $pythonVersion = if ($pythonLines.Count -gt 1) { $pythonLines[1].ToString() } else { '' }
    $report.actual.python = [ordered]@{ launcher = $pythonCommand.Source; executable = $pythonExe; version = $pythonVersion }
    Add-Check 'python_3_12_3_x64' ($pythonVersion -match '^3\.12\.3') $pythonVersion
} else {
    Add-Check 'python_3_12_3_x64' $false "未找到 Python Launcher (py)；安装 $($versions.candidates.python.windowsInstaller)。"
}

if ($goCommand) {
    $goPath = (& $goCommand.Source env GOPATH).Trim()
    $wailsPath = Join-Path -Path $goPath -ChildPath 'bin\wails3.exe'
    if (Test-Path $wailsPath) {
        $wailsVersionProcess = New-Object System.Diagnostics.Process
        $wailsVersionProcess.StartInfo.FileName = $wailsPath
        $wailsVersionProcess.StartInfo.Arguments = 'version'
        $wailsVersionProcess.StartInfo.UseShellExecute = $false
        $wailsVersionProcess.StartInfo.RedirectStandardOutput = $true
        $wailsVersionProcess.StartInfo.RedirectStandardError = $true
        [void]$wailsVersionProcess.Start()
        $wailsVersionStandardOutput = $wailsVersionProcess.StandardOutput.ReadToEnd()
        $wailsVersionStandardError = $wailsVersionProcess.StandardError.ReadToEnd()
        $wailsVersionProcess.WaitForExit()
        $wailsVersion = "$wailsVersionStandardOutput`n$wailsVersionStandardError".Trim()
        $wailsVersionDetail = "exitCode=$($wailsVersionProcess.ExitCode); version=$wailsVersion"
        $report.actual.wails = [ordered]@{ command = $wailsPath; version = $wailsVersion; exitCode = $wailsVersionProcess.ExitCode }
        Add-Check 'wails_v3_beta_8' ($wailsVersionProcess.ExitCode -eq 0 -and $wailsVersion -match [regex]::Escape($versions.candidates.wails.version)) $wailsVersionDetail
    } else {
        Add-Check 'wails_v3_beta_8' $false "未找到 $wailsPath；运行 .\scripts\Install-WailsCli.ps1"
    }
} else {
    Add-Check 'wails_v3_beta_8' $false 'Go 缺失，因此无法定位 wails3。'
}

$runtimeRoot = Join-Path $root ".tools\webview2-fixed-$($versions.candidates.webview2.version)-$($versions.candidates.webview2.architecture)"
$browser = Get-ChildItem -Path $runtimeRoot -Filter 'msedgewebview2.exe' -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
if ($browser) {
    $browserVersion = $browser.VersionInfo.FileVersion
    $report.actual.webview2 = [ordered]@{ browserPath = $browser.DirectoryName; executable = $browser.FullName; version = $browserVersion }
    Add-Check 'webview2_fixed_151_0_4129_78_x64' ($browserVersion -match [regex]::Escape($versions.candidates.webview2.version)) $browserVersion
} else {
    Add-Check 'webview2_fixed_151_0_4129_78_x64' $false '未找到 Fixed Version Runtime；运行 .\scripts\Install-WebView2FixedRuntime.ps1'
}

$path = Join-Path $evidence ("environment-{0}.json" -f (Get-Date -Format 'yyyyMMddTHHmmssZ'))
$report | ConvertTo-Json -Depth 8 | Set-Content -Path $path -Encoding UTF8
Write-Host "环境报告：$path"
if ($report.errors.Count -gt 0) {
    Write-Error ($report.errors -join [Environment]::NewLine)
    exit 1
}
exit 0
