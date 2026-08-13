[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$configPath = Join-Path $root '.spike-run.json'
if (-not (Test-Path $configPath)) { throw '未找到运行配置；先运行 .\scripts\Start-Spike.ps1' }
$runDir = (Get-Content $configPath -Raw | ConvertFrom-Json).evidenceDirectory

function Ask-Result([string]$id, [string]$instruction, [string]$question) {
    Write-Host ''
    Write-Host "[$id] $instruction" -ForegroundColor Cyan
    do { $result = (Read-Host "$question 输入 PASS / FAIL / BLOCKED").Trim().ToUpperInvariant() } while ($result -notin @('PASS', 'FAIL', 'BLOCKED'))
    $evidence = Read-Host '截图、录屏或补充日志的文件名（没有则留空）'
    return [ordered]@{ id = $id; result = $result; evidence = $evidence; recordedAt = (Get-Date).ToUniversalTime().ToString('o') }
}

$observations = @()
$observations += Ask-Result 'tray_close_keeps_host' '依据人工观察清单 A1：关闭主窗口后托盘图标和宿主进程仍存在。' '这项观察的结果是？'
$observations += Ask-Result 'tray_restores_main' '依据人工观察清单 A2：通过托盘恢复主窗口并获得前台焦点。' '这项观察的结果是？'
$observations += Ask-Result 'overlay_show_hide' '依据人工观察清单 A3：置顶演示小窗可显示和隐藏。' '这项观察的结果是？'
$observations += Ask-Result 'overlay_stays_on_top' '依据人工观察清单 A4：置顶演示小窗在普通窗口上方，隐藏不改变测试替身。' '这项观察的结果是？'
$observations += Ask-Result 'notification_action_activates_context' '依据人工观察清单 A5：通知操作激活主窗口。' '这项观察的结果是？'
$observations += Ask-Result 'autostart_real_login' '依据人工观察清单 A6：真实注销并重新登录后只出现一个宿主和一个测试替身，且已禁用开机启动。' '这项观察的结果是？'

$path = Join-Path $runDir 'manual-observations.json'
$observations | ConvertTo-Json -Depth 5 | Set-Content -Path $path -Encoding UTF8
Write-Host "人工观察已保存：$path"
