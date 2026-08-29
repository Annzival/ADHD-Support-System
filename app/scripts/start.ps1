#Requires -Version 5.1
<#
.SYNOPSIS
    一键启动执行支持 MVP（Python 智能体核心 + Wails v3 桌面宿主）。

.DESCRIPTION
    依次完成：准备 Python 虚拟环境 → 安装核心依赖 → 构建桌面宿主 → 启动应用。
    智能体核心由宿主自动拉起，并通过一次性 bootstrap 文件完成回环端点与临时令牌交接。
    本脚本不接触任何权威状态，也不读写数据库。

.PARAMETER Rebuild
    强制重新构建桌面宿主。

.PARAMETER SkipBuild
    跳过构建，直接启动已有的宿主二进制。

.PARAMETER CheckOnly
    只做环境与构建检查，不启动应用。

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\start.ps1
#>
[CmdletBinding()]
param(
    [switch]$Rebuild,
    [switch]$SkipBuild,
    [switch]$CheckOnly
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Write-Step {
    param([Parameter(Mandatory)][string]$Message)
    Write-Host "[执行支持] $Message" -ForegroundColor Cyan
}

function Write-Ok {
    param([Parameter(Mandatory)][string]$Message)
    Write-Host "[执行支持] $Message" -ForegroundColor Green
}

function Get-PythonLauncher {
    $candidates = @(
        @{ Exe = 'python'; Prefix = @() },
        @{ Exe = 'py'; Prefix = @('-3') },
        @{ Exe = 'python3'; Prefix = @() }
    )
    foreach ($candidate in $candidates) {
        if (-not (Get-Command $candidate.Exe -ErrorAction SilentlyContinue)) { continue }
        $arguments = @($candidate.Prefix) + @('-c', 'import sys;print("%d.%d" % sys.version_info[:2])')
        try {
            $output = & $candidate.Exe @arguments 2>$null
            if ($LASTEXITCODE -eq 0 -and $output -match '^3\.(\d+)$' -and [int]$Matches[1] -ge 12) {
                return $candidate
            }
        }
        catch { continue }
    }
    throw '未找到 Python 3.12 或更高版本。请先安装 Python 3.12+ 并加入 PATH。'
}

# --- 路径解析：脚本位于 app/scripts/ ---------------------------------------
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$appRoot = Split-Path -Parent $scriptDir
$coreDir = Join-Path $appRoot 'agent_core'
$desktopDir = Join-Path $appRoot 'desktop'
$venvDir = Join-Path $coreDir '.venv'
$venvPython = Join-Path $venvDir 'Scripts\python.exe'
$hostExe = Join-Path $desktopDir 'bin\app-desktop.exe'

if (-not (Test-Path $coreDir)) { throw "找不到智能体核心目录：$coreDir" }
if (-not (Test-Path $desktopDir)) { throw "找不到桌面宿主目录：$desktopDir" }

# --- 1. Python 虚拟环境 -----------------------------------------------------
if (-not (Test-Path $venvPython)) {
    Write-Step '首次运行：创建 Python 虚拟环境…'
    $python = Get-PythonLauncher
    $venvArgs = @($python.Prefix) + @('-m', 'venv', $venvDir)
    & $python.Exe @venvArgs
    if ($LASTEXITCODE -ne 0) { throw '创建虚拟环境失败。' }
    Write-Ok '虚拟环境已创建。'
}

# --- 2. 依赖 ---------------------------------------------------------------
Write-Step '检查智能体核心依赖…'
& $venvPython -c 'import pydantic_ai' 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Step '安装依赖（首次运行需要几分钟）…'
    & $venvPython -m pip install --quiet --upgrade pip
    if ($LASTEXITCODE -ne 0) { throw '升级 pip 失败。' }
    & $venvPython -m pip install --quiet -e "${coreDir}[dev]"
    if ($LASTEXITCODE -ne 0) { throw '安装依赖失败。' }
    Write-Ok '依赖已安装。'
}
else {
    Write-Ok '依赖已就绪。'
}

# --- 3. 构建桌面宿主 -------------------------------------------------------
if (-not $SkipBuild) {
    if ($Rebuild -or -not (Test-Path $hostExe)) {
        if (-not (Get-Command 'go' -ErrorAction SilentlyContinue)) {
            throw '未找到 Go 工具链。请安装 Go 1.25+ 后重试，或使用 -SkipBuild 启动已有二进制。'
        }
        Write-Step '构建桌面宿主…'
        Push-Location $desktopDir
        try {
            & go build -o $hostExe .
            if ($LASTEXITCODE -ne 0) { throw '构建桌面宿主失败。' }
        }
        finally { Pop-Location }
        Write-Ok '桌面宿主已构建。'
    }
    else {
        Write-Ok '桌面宿主已是最新（使用 -Rebuild 强制重建）。'
    }
}

if (-not (Test-Path $hostExe)) { throw "找不到宿主二进制：$hostExe" }
Write-Ok '环境检查通过。'

# --- 4. 启动 ---------------------------------------------------------------
if ($CheckOnly) {
    Write-Step '已按 -CheckOnly 跳过启动。'
    return
}

Write-Step '启动执行支持…'
Write-Host '  应用会在新窗口中打开；关闭窗口即退出，智能体核心随之停止。' -ForegroundColor DarkGray
Start-Process -FilePath $hostExe -WorkingDirectory $desktopDir
Write-Ok '已启动。'
