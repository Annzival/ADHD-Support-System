[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$failures = @()

foreach ($script in Get-ChildItem -LiteralPath $PSScriptRoot -Filter '*.ps1' -File) {
    $raw = [System.IO.File]::ReadAllBytes($script.FullName)
    if (@($raw | Where-Object { $_ -gt 127 }).Count -gt 0) {
        $failures += "[$($script.Name)] script must stay ASCII for Windows PowerShell 5.1"
        continue
    }
    $tokens = $null
    $errors = $null
    [System.Management.Automation.Language.Parser]::ParseFile($script.FullName, [ref]$tokens, [ref]$errors) | Out-Null
    foreach ($error in @($errors | Where-Object { $null -ne $_ })) {
        $failures += "[$($script.Name)] $($error.Message)"
    }
}

try {
    Get-Content -LiteralPath (Join-Path $root 'versions.json') -Raw -Encoding UTF8 | ConvertFrom-Json | Out-Null
}
catch {
    $failures += "[versions.json] $($_.Exception.Message)"
}

if ($failures.Count -gt 0) {
    $failures | ForEach-Object { Write-Error $_ }
    exit 1
}

Write-Host "PowerShell parser and version manifest: OK"
