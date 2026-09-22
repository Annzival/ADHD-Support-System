param([Parameter(Mandatory=$true)][string]$TestPython)
$ErrorActionPreference = 'Stop'
$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../../..'))
$scriptPath = Join-Path $repoRoot 'scripts/acceptance/windows-smoke.ps1'
$tokens = $null
$errors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile($scriptPath, [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw 'Script parse failed.' }
# Load production functions without executing Windows-only checks or starting a desktop.
$functions = $ast.FindAll({ param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] }, $false)
foreach ($function in $functions) { . ([ScriptBlock]::Create($function.Extent.Text)) }
Copy-Item Function:\Invoke-Tool Function:\Invoke-NativeTool
$script:Calls = @()
$script:DiscoveryMode = 'Interpreter'
function Invoke-Tool([string]$Executable, [string[]]$Arguments, [string]$WorkingDirectory = $repoRoot) {
    $script:Calls += ,@($Executable, $Arguments)
    if ($script:DiscoveryMode -eq 'PythonOnly' -and $Executable -eq 'py') { throw 'Launcher missing.' }
    if ($script:DiscoveryMode -in @('WrongVersion','WrongBits')) {
        $version = '3.12.3'
        $bits = 64
        if ($script:DiscoveryMode -eq 'WrongVersion') { $version = '3.13.0' }
        if ($script:DiscoveryMode -eq 'WrongBits') { $bits = 32 }
        return (@{ executable = $TestPython; version = $version; bits = $bits } | ConvertTo-Json -Compress)
    }
    if ($script:DiscoveryMode -eq 'Launcher' -and $Executable -eq 'py' -and $Arguments[0] -eq '-3.12') {
        $Arguments = $Arguments[1..($Arguments.Count - 1)]
    }
    if ($Executable -in @('py','python','python3')) { $Executable = $TestPython }
    Invoke-NativeTool $Executable $Arguments $WorkingDirectory
}
$discovery = $ast.FindAll({
    param($node)
    $node -is [Management.Automation.Language.IfStatementAst] -and
    $node.Extent.Text -match '^if \(-not \$PythonExecutable\)' -and
    $node.Extent.Text -match 'import sys;print|Resolve-PythonExecutable'
}, $true)
if ($discovery.Count -ne 1) { throw 'Expected one production Python discovery call site.' }
$PythonExecutable = ''
. ([ScriptBlock]::Create($discovery[0].Extent.Text))
if (-not [IO.Path]::IsPathRooted($PythonExecutable) -or -not (Test-Path -LiteralPath $PythonExecutable)) {
    throw 'Discovery did not return a usable absolute interpreter path.'
}
$actual = Invoke-NativeTool $PythonExecutable @('-c','import platform,struct;print(platform.python_version());print(struct.calcsize(chr(80))*8)')
if ($actual -notmatch '3\.12\.3\s+64') { throw 'Discovery bypassed the locked runtime.' }
Write-Host 'PASS: py mapped to an interpreter resolves without requiring launcher selectors.'

foreach ($mode in @('Launcher','PythonOnly')) {
    $script:DiscoveryMode = $mode
    $script:Calls = @()
    $PythonExecutable = ''
    . ([ScriptBlock]::Create($discovery[0].Extent.Text))
    if (-not (Test-Path -LiteralPath $PythonExecutable)) { throw 'No interpreter resolved.' }
    if ($mode -eq 'Launcher' -and $script:Calls.Count -ne 1) { throw 'Launcher success should stop discovery.' }
    if ($mode -eq 'PythonOnly' -and $script:Calls[2][0] -ne 'python') { throw 'Missing py did not fall back to python.' }
    Write-Host ('PASS: ' + $mode)
}
foreach ($mode in @('WrongVersion','WrongBits')) {
    $script:DiscoveryMode = $mode
    try {
        $null = Resolve-PythonExecutable
        throw 'Unexpectedly accepted an incompatible runtime.'
    } catch {
        if ($_.Exception.Message -notlike 'Python 3.12.3 x64 was not found.*-PythonExecutable*') { throw }
    }
    Write-Host ('PASS: rejects ' + $mode + ' with an explicit-path remedy.')
}
$script:Calls = @()
$PythonExecutable = $TestPython
. ([ScriptBlock]::Create($discovery[0].Extent.Text))
if ($PythonExecutable -ne $TestPython -or $script:Calls.Count -ne 0) { throw 'Explicit executable should bypass discovery.' }
Write-Host 'PASS: explicit PythonExecutable bypasses discovery; existing version gate remains in the caller.'
