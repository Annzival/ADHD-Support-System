param(
    [ValidateSet('I01','I02')][string]$Stage = 'I01',
    [ValidateSet('Run','Resume','Snapshot','RestartCore','Collect','BeforeReboot','AfterReboot')][string]$Mode = 'Run',
    [ValidateSet('ConfirmedDuration','MissingDuration','MultiplePlans','ShortWindow','WithoutWindow')][string]$Case = 'ConfirmedDuration',
    [string]$WebView2Path,
    [string]$DataDirectory,
    [string]$PythonExecutable,
    [int]$StartDelay = 45,
    [int]$DurationSeconds = 60,
    [int]$GraceSeconds = 30,
    [int]$SecondDelay = 90
)
$ErrorActionPreference = 'Stop'
$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
if (-not [Environment]::Is64BitOperatingSystem -or [Environment]::OSVersion.Platform -ne 'Win32NT') {
    throw 'Windows 10 22H2 x64 is required. Linux results are not desktop evidence.'
}

# Capture both native streams without PowerShell 5.1 NativeCommandError conversion.
function Invoke-Tool([string]$Executable, [string[]]$Arguments, [string]$WorkingDirectory = $repoRoot) {
    $info = New-Object Diagnostics.ProcessStartInfo
    $info.FileName = $Executable
    $info.WorkingDirectory = $WorkingDirectory
    $info.UseShellExecute = $false
    $info.RedirectStandardOutput = $true
    $info.RedirectStandardError = $true
    $quoted = @($Arguments | ForEach-Object {
        if ($_ -match '"' -or $_ -match '[\r\n]') { throw 'Quotes/newlines are not allowed in tool arguments.' }
        '"' + ($_ -replace '(\\+)$', '$1$1') + '"'
    })
    $info.Arguments = $quoted -join ' '
    $process = New-Object Diagnostics.Process
    $process.StartInfo = $info
    [void]$process.Start()
    $outTask = $process.StandardOutput.ReadToEndAsync()
    $errTask = $process.StandardError.ReadToEndAsync()
    $process.WaitForExit()
    $outText = $outTask.Result
    $errText = $errTask.Result
    if ($process.ExitCode -ne 0) { throw ('Tool failed: ' + $Executable + "`n" + $outText + $errText) }
    if ($errText) { Write-Host $errText }
    return ($outText + $errText).Trim()
}
function Resolve-PythonExecutable {
    # A command named py is not necessarily the Windows Python Launcher.
    # Probe the selected interpreter itself before accepting any discovery candidate.
    $probe = 'import sys,platform,struct,json;print(json.dumps(dict(executable=sys.executable,version=platform.python_version(),bits=struct.calcsize(chr(80))*8)))'
    $candidates = @(
        @{ executable = 'py'; prefix = @('-3.12') },
        @{ executable = 'py'; prefix = @() },
        @{ executable = 'python'; prefix = @() },
        @{ executable = 'python3'; prefix = @() }
    )
    foreach ($candidate in $candidates) {
        try {
            $arguments = @($candidate.prefix) + @('-c', $probe)
            $runtime = (Invoke-Tool $candidate.executable $arguments) | ConvertFrom-Json
            if ($runtime.version -eq '3.12.3' -and $runtime.bits -eq 64 -and
                [IO.Path]::IsPathRooted($runtime.executable) -and
                (Test-Path -LiteralPath $runtime.executable -PathType Leaf)) {
                return $runtime.executable
            }
        } catch {
            # Missing commands and unsupported launcher selectors are discovery misses.
            # The caller's final version check still applies to the selected executable.
        }
    }
    throw 'Python 3.12.3 x64 was not found. Pass -PythonExecutable with its full python.exe path; no runtime was installed or changed.'
}
function Write-Json([string]$Path, $Value) {
    $text = $Value | ConvertTo-Json -Depth 40
    [IO.File]::WriteAllText($Path, $text, (New-Object Text.UTF8Encoding($false)))
}
function Require-Data {
    if (-not $DataDirectory) { throw 'Provide -DataDirectory from the Run output.' }
    $script:DataDirectory = [IO.Path]::GetFullPath($DataDirectory)
    $parent = [IO.Path]::GetFullPath((Join-Path $repoRoot '.i01-runs')) + [IO.Path]::DirectorySeparatorChar
    if (-not $DataDirectory.StartsWith($parent, [StringComparison]::OrdinalIgnoreCase)) { throw 'Data must be in this checkout .i01-runs directory.' }
    if (-not (Test-Path (Join-Path $DataDirectory 'run.json'))) { throw 'Run identity missing.' }
}
function Read-Run { return Get-Content -LiteralPath (Join-Path $DataDirectory 'run.json') -Raw -Encoding UTF8 | ConvertFrom-Json }
function Save-Snapshot([string]$Label) {
    $snapshot = Invoke-Tool $PythonExecutable @('-m','agent_core','inspect','--data-dir',$DataDirectory)
    $parsed = $snapshot | ConvertFrom-Json
    Write-Json (Join-Path $DataDirectory ($Label + '.json')) $parsed
}
function Start-Desktop {
    $binary = Join-Path $repoRoot 'desktop\bin\i01-desktop.exe'
    $quotedArgs = @('--python', $PythonExecutable, '--root', $repoRoot, '--data-dir', $DataDirectory, '--webview2', $WebView2Path) | ForEach-Object {
        if ($_ -match '"' -or $_ -match '[\r\n]') { throw 'Quotes/newlines in paths are not supported.' }
        '"' + ($_ -replace '(\\+)$', '$1$1') + '"'
    }
    Start-Process -FilePath $binary -ArgumentList ($quotedArgs -join ' ') -WorkingDirectory $repoRoot | Out-Null
}

if ($Mode -ne 'Run') {
    Require-Data
    $run = Read-Run
    if ($run.stage) { $Stage = $run.stage }
    if (-not $PythonExecutable) { $PythonExecutable = $run.pythonExecutable }
    if (-not $WebView2Path) { $WebView2Path = $run.webView2Path }
    if (Invoke-Tool 'git' @('status','--porcelain','--untracked-files=normal')) { throw 'Use the clean recorded checkpoint.' }
    $commit = Invoke-Tool 'git' @('rev-parse','HEAD')
    if ($commit -ne $run.commit) { throw 'Checkout differs from run commit. Return to the recorded checkpoint.' }
    if ($Mode -in @('BeforeReboot','AfterReboot')) {
        $boot = (Get-CimInstance Win32_OperatingSystem).LastBootUpTime.ToUniversalTime().ToString('o')
        $corePattern = [Regex]::Escape($DataDirectory)
        $cores = @(Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match '-m agent_core serve' -and $_.CommandLine -match $corePattern })
        $hosts = @(Get-Process -Name 'i01-desktop' -ErrorAction SilentlyContinue)
        $state = (Invoke-Tool $PythonExecutable @('-m','agent_core','inspect','--data-dir',$DataDirectory) | ConvertFrom-Json).state
        $record = [ordered]@{ boot = $boot; hostCount = $hosts.Count; coreCount = $cores.Count; databaseId = $state.database_id; commit = $commit }
        if ($Mode -eq 'AfterReboot') {
            $prior = Get-Content (Join-Path $DataDirectory 'before-reboot.json') -Raw -Encoding UTF8 | ConvertFrom-Json
            if ($prior.boot -eq $boot) { throw 'A real PC reboot has not been observed.' }
            if ($prior.databaseId -ne $state.database_id -or $hosts.Count -ne 1 -or $cores.Count -ne 1) { throw 'Database identity or process count mismatch.' }
        } elseif ($hosts.Count -ne 1 -or $cores.Count -ne 1) { throw 'Expected exactly one host and Core before reboot.' }
        $label = if ($Mode -eq 'BeforeReboot') { 'before-reboot' } else { 'after-reboot' }
        Write-Json (Join-Path $DataDirectory ($label + '.json')) $record
        Save-Snapshot ($label + '-state')
        Write-Host 'Reboot evidence saved locally; review domain state separately.'
        exit 0
    }
    if ($Mode -eq 'Snapshot') {
        Save-Snapshot ('snapshot-' + [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffZ'))
        Write-Host 'Snapshot saved locally. It contains only this synthetic fixture.'
        exit 0
    }
    if ($Mode -eq 'RestartCore') {
        $coreScriptPattern = [Regex]::Escape($DataDirectory)
        $processes = @(Get-CimInstance Win32_Process | Where-Object {
            $_.CommandLine -match '-m agent_core serve' -and $_.CommandLine -match $coreScriptPattern
        })
        if ($processes.Count -ne 1) { throw 'Expected exactly one Core for this data directory; nothing stopped.' }
        Save-Snapshot 'before-core-restart'
        Stop-Process -Id $processes[0].ProcessId
        Write-Host 'Core stopped once. Observe reconnect, unchanged session ID and checkpoint time, then run Snapshot.'
        exit 0
    }
    if ($Mode -eq 'Resume') {
        $binary = Join-Path $repoRoot 'desktop\bin\i01-desktop.exe'
        if ((Get-FileHash $binary -Algorithm SHA256).Hash -ne $run.binarySha256) { throw 'Binary differs from run identity.' }
        Start-Desktop
        Write-Host 'Resumed the same development database. Old notifications must not be replayed.'
        exit 0
    }
    if ($Mode -eq 'Collect') {
        $hosts = @(Get-Process -Name 'i01-desktop' -ErrorAction SilentlyContinue)
        if ($hosts.Count -gt 0) { throw 'Exit the desktop from its tray menu before Collect.' }
        Save-Snapshot 'final-state'
        $observations = Get-Content (Join-Path $DataDirectory 'observations.json') -Raw -Encoding UTF8 | ConvertFrom-Json
        $allowedObservations = @('arrivalAndCorrectNotification','startAndFirstCheckpoint','cancelDurationLeavesPending','completionBeforeCheckpoint','completionAfterCheckpoint','finishClosure','skipClosure','nativeCloseSkipsClosure','staleNotificationShowsCurrentContext','coreRestartKeepsSameSessionAndCheckpoint','awaitingClosureSurvivesRestart','endedStateSurvivesRestart','overlayCloseAndReopen')
        if ($Stage -eq 'I02') { $allowedObservations += @('alreadyStarted','retrospectiveComplete','reschedule','skipToday','weakFollowup','singleForeground','continueCheckpoint','pausePacket','automaticClosure','unknownTrackingEnd','factCorrection','resumePacket','oldVersionChoice','deferRecovery','recoverySwitch','singleInstance','autostart','pcRestart','processSupervisor','recoveryCarrier') }
        foreach ($property in $observations.PSObject.Properties) {
            if ($property.Name -notin $allowedObservations -or $property.Value -notin @('NOT_RUN','PASS','FAIL','BLOCKED')) { throw 'Observations must use the template fields and NOT_RUN/PASS/FAIL/BLOCKED only.' }
        }
        if (@($observations.PSObject.Properties).Count -ne $allowedObservations.Count) { throw 'Observation fields are missing.' }
        $files = @('run.json','environment.json','automatic-tests.txt','observations.json','final-state.json','desktop-evidence.jsonl')
        $files += @(Get-ChildItem -LiteralPath $DataDirectory -Filter '*reboot*.json' | ForEach-Object { $_.Name })
        $files += @(Get-ChildItem -LiteralPath $DataDirectory -Filter 'snapshot-*.json' | ForEach-Object { $_.Name })
        $hashes = @{}
        foreach ($name in $files) {
            $path = Join-Path $DataDirectory $name
            if (Test-Path $path) { $hashes[$name] = (Get-FileHash $path -Algorithm SHA256).Hash }
        }
        $final = Get-Content (Join-Path $DataDirectory 'final-state.json') -Raw -Encoding UTF8 | ConvertFrom-Json
        $summary = [ordered]@{
            schemaVersion = 1; stage = $Stage; status = 'AWAITING_EVIDENCE_REVIEW'; commit = $run.commit
            case = $run.case; binarySha256 = $run.binarySha256; environment = $run.environment
            databaseId = $final.state.database_id; activeSession = $final.state.active_session
            sessions = $final.state.sessions; evidence = $final.state.evidence
            observations = $observations; files = $hashes
        }
        Write-Json (Join-Path $DataDirectory 'evidence-summary.json') $summary
        Write-Host ('Return this synthetic summary: ' + (Join-Path $DataDirectory 'evidence-summary.json'))
        Write-Host 'No automatic stage PASS is declared. Preserve local source files for review; do not publish run.json or the database.'
        exit 0
    }
}

if (-not $WebView2Path) { throw 'Provide -WebView2Path for fixed 151.0.4129.78 x64.' }
if (-not $PythonExecutable) { $PythonExecutable = Resolve-PythonExecutable }
$PythonExecutable = [IO.Path]::GetFullPath($PythonExecutable)
$WebView2Path = [IO.Path]::GetFullPath($WebView2Path)
$windows = Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion'
if ($windows.DisplayVersion -ne '22H2' -or $windows.CurrentBuildNumber -ne '19045') { throw 'Locked Windows 10 22H2 / 19045 required.' }
$pythonInfo = (Invoke-Tool $PythonExecutable @('-c','import platform,struct,sqlite3,json;print(json.dumps(dict(version=platform.python_version(),bits=struct.calcsize(chr(80))*8,sqlite=sqlite3.sqlite_version)))')) | ConvertFrom-Json
if ($pythonInfo.version -ne '3.12.3' -or $pythonInfo.bits -ne 64) { throw 'Locked Python 3.12.3 x64 required.' }
$goVersion = Invoke-Tool 'go' @('version')
if ($goVersion -ne 'go version go1.25.0 windows/amd64') { throw 'Locked Go 1.25.0 windows/amd64 required.' }
$webviewFile = Join-Path $WebView2Path 'msedgewebview2.exe'
$peStream = [IO.File]::OpenRead($webviewFile)
try {
    $reader = New-Object IO.BinaryReader($peStream)
    $peStream.Position = 0x3c
    $peOffset = $reader.ReadInt32()
    $peStream.Position = $peOffset + 4
    if ($reader.ReadUInt16() -ne 0x8664) { throw 'Fixed WebView2 must be x64.' }
} finally { $peStream.Dispose() }
$webviewVersion = (Get-Item (Join-Path $WebView2Path 'msedgewebview2.exe')).VersionInfo.FileVersion
if ($webviewVersion -ne '151.0.4129.78') { throw 'Locked fixed WebView2 151.0.4129.78 required.' }
$dirty = Invoke-Tool 'git' @('status','--porcelain','--untracked-files=normal')
if ($dirty) { throw 'Use a clean checkpoint checkout before collecting evidence.' }
$commit = Invoke-Tool 'git' @('rev-parse','HEAD')
if (@(Get-Process -Name 'i01-desktop' -ErrorAction SilentlyContinue).Count -gt 0) { throw 'Exit the previous I-01 desktop from its tray before Run.' }
$environment = [ordered]@{ windows = '10.0.19045'; displayVersion = '22H2'; ubr = $windows.UBR; bits = 64; python = $pythonInfo; go = $goVersion; wails = 'v3.0.0-beta.8'; webView2 = $webviewVersion }
$testOutput = Invoke-Tool $PythonExecutable @('-m','unittest','discover','-s','tests/acceptance','-v')
$env:I01_TEST_PYTHON = $PythonExecutable
$goTests = Invoke-Tool 'go' @('test','-v','./...') (Join-Path $repoRoot 'desktop')
$moduleVersion = Invoke-Tool 'go' @('list','-m','-f','{{.Version}}','github.com/wailsapp/wails/v3') (Join-Path $repoRoot 'desktop')
if ($moduleVersion -ne 'v3.0.0-beta.8') { throw 'Wails version drift.' }
$binaryDirectory = Join-Path $repoRoot 'desktop\bin'
[void](New-Item -ItemType Directory -Path $binaryDirectory -Force)
$binary = Join-Path $binaryDirectory 'i01-desktop.exe'
[void](Invoke-Tool 'go' @('build','-trimpath','-buildvcs=true','-o',$binary,'.') (Join-Path $repoRoot 'desktop'))
if (-not $DataDirectory) { $DataDirectory = Join-Path $repoRoot ('.i01-runs\' + [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffZ') + '-' + $Case) }
$DataDirectory = [IO.Path]::GetFullPath($DataDirectory)
$allowedParent = [IO.Path]::GetFullPath((Join-Path $repoRoot '.i01-runs')) + [IO.Path]::DirectorySeparatorChar
if (-not $DataDirectory.StartsWith($allowedParent, [StringComparison]::OrdinalIgnoreCase)) { throw 'Use a new directory under .i01-runs.' }
$seedArgs = @('-m','agent_core','seed','--data-dir',$DataDirectory,'--confirm-development-fixture','--start-delay',"$StartDelay")
if ($Stage -eq 'I02') {
    $seedArgs += @('--duration',"$DurationSeconds",'--grace-seconds',"$GraceSeconds")
    if ($Case -eq 'MultiplePlans') { $seedArgs += @('--second-delay',"$SecondDelay",'--second-version','Q') }
    if ($Case -eq 'ShortWindow') { $seedArgs += @('--window-seconds','180') }
    if ($Case -eq 'WithoutWindow') { $seedArgs += @('--window-seconds','0') }
}
if ($Case -eq 'MissingDuration') { $seedArgs += '--without-duration' }
[void](Invoke-Tool $PythonExecutable $seedArgs)
Write-Json (Join-Path $DataDirectory 'environment.json') $environment
Write-Json (Join-Path $DataDirectory 'run.json') ([ordered]@{ commit = $commit; stage = $Stage; case = $Case; binarySha256 = (Get-FileHash $binary -Algorithm SHA256).Hash; pythonExecutable = $PythonExecutable; webView2Path = $WebView2Path; environment = $environment })
[IO.File]::WriteAllText((Join-Path $DataDirectory 'automatic-tests.txt'), ($testOutput + "`n" + $goTests), (New-Object Text.UTF8Encoding($false)))
Write-Json (Join-Path $DataDirectory 'observations.json') ([ordered]@{
    arrivalAndCorrectNotification = 'NOT_RUN'; startAndFirstCheckpoint = 'NOT_RUN'
    cancelDurationLeavesPending = 'NOT_RUN'; completionBeforeCheckpoint = 'NOT_RUN'
    completionAfterCheckpoint = 'NOT_RUN'; finishClosure = 'NOT_RUN'; skipClosure = 'NOT_RUN'
    nativeCloseSkipsClosure = 'NOT_RUN'; staleNotificationShowsCurrentContext = 'NOT_RUN'
    coreRestartKeepsSameSessionAndCheckpoint = 'NOT_RUN'; awaitingClosureSurvivesRestart = 'NOT_RUN'
    endedStateSurvivesRestart = 'NOT_RUN'; overlayCloseAndReopen = 'NOT_RUN'
})
if ($Stage -eq 'I02') {
    $observations = Get-Content (Join-Path $DataDirectory 'observations.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    foreach ($name in @('alreadyStarted','retrospectiveComplete','reschedule','skipToday','weakFollowup','singleForeground','continueCheckpoint','pausePacket','automaticClosure','unknownTrackingEnd','factCorrection','resumePacket','oldVersionChoice','deferRecovery','recoverySwitch','singleInstance','autostart','pcRestart','processSupervisor','recoveryCarrier')) { $observations | Add-Member NoteProperty $name 'NOT_RUN' }
    Write-Json (Join-Path $DataDirectory 'observations.json') $observations
}
Start-Desktop
Write-Host ('DataDirectory: ' + $DataDirectory)
Write-Host 'Follow docs/implementation/windows-i01.md or windows-i02.md for the selected stage. Set only observed entries to PASS or FAIL; leave others NOT_RUN.'
Write-Host 'Exit via tray when finished. Use Resume for persistence checks, Collect for the return summary.'
