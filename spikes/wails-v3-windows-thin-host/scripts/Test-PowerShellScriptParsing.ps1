[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$scripts = Get-ChildItem -LiteralPath $PSScriptRoot -Filter '*.ps1' -File
$failures = @()

foreach ($script in $scripts) {
    $tokens = $null
    $errors = $null
    [System.Management.Automation.Language.Parser]::ParseFile($script.FullName, [ref]$tokens, [ref]$errors) | Out-Null
    foreach ($error in @($errors | Where-Object { $null -ne $_ })) {
        $failures += "[$($script.Name)] $($error.Message)"
    }
}

if ($failures.Count -gt 0) {
    $failures | ForEach-Object { Write-Error $_ }
    exit 1
}

Write-Host "PowerShell parser: OK ($($scripts.Count) scripts)"
