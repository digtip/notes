# TeleAgent IM 完成通知 —— Windows 安装脚本
# 用法: 在 PowerShell 中执行  powershell -ExecutionPolicy Bypass -File install.ps1
# 作用范围: 仅用户家目录（%APPDATA%\TeleAgent\users\<账号>\skills\im-notify 与 $HOME\bin），不碰系统目录。
# 回退:     删除上述两处文件即可。

$ErrorActionPreference = "Stop"
$SkillName = "im-notify"
$SrcDir = Split-Path -Parent $MyInvocation.MyCommand.Path

function Get-OwnerDir {
    $candidates = @()
    if ($env:TELEAGENT_HOME) { $candidates += $env:TELEAGENT_HOME }
    if ($env:LOCALAPPDATA) { $candidates += (Join-Path $env:LOCALAPPDATA "TeleAgent") }
    if ($env:APPDATA) { $candidates += (Join-Path $env:APPDATA "TeleAgent") }
    foreach ($base in $candidates) {
        $f = Join-Path $base "current-owner.json"
        if (Test-Path $f) {
            try { return (Get-Content $f -Raw | ConvertFrom-Json).ownerDir } catch { }
        }
    }
    return ""
}

function Get-SkillsRoot([string]$ownerDir) {
    $candidates = @()
    if ($env:TELEAGENT_SKILLS_HOME) { $candidates += $env:TELEAGENT_SKILLS_HOME }
    if ($env:APPDATA) { $candidates += (Join-Path $env:APPDATA "TeleAgent") }
    if ($env:LOCALAPPDATA) { $candidates += (Join-Path $env:LOCALAPPDATA "TeleAgent") }
    foreach ($base in $candidates) {
        $p = Join-Path $base "users\$ownerDir\skills"
        if (Test-Path $p) { return $p }
    }
    return (Join-Path $env:APPDATA "TeleAgent\users\$ownerDir\skills")
}

$ownerDir = Get-OwnerDir
if (-not $ownerDir) {
    Write-Error "找不到 current-owner.json，请先启动一次客户端，或设置 TELEAGENT_HOME"
    exit 1
}
$skillsRoot = Get-SkillsRoot $ownerDir
$skillDir = Join-Path $skillsRoot $SkillName
Write-Host "==> 账号: $ownerDir"
Write-Host "==> 目标技能目录: $skillDir"

# 1) 独立脚本
$binDir = Join-Path $HOME "bin"
if (-not (Test-Path $binDir)) { New-Item -ItemType Directory -Path $binDir | Out-Null }
Copy-Item (Join-Path $SrcDir "notify.py") (Join-Path $binDir "notify.py") -Force
Write-Host "==> 已安装脚本: $(Join-Path $binDir 'notify.py')"

# 2) 技能
New-Item -ItemType Directory -Path (Join-Path $skillDir "scripts") -Force | Out-Null
Copy-Item (Join-Path $SrcDir "notify.py") (Join-Path $skillDir "scripts\notify.py") -Force
$skillMd = Get-Content (Join-Path $SrcDir "skill\$SkillName\SKILL.md") -Raw
$skillMd = $skillMd.Replace("__SKILL_DIR__", $skillDir.Replace("\", "/"))
Set-Content -Path (Join-Path $skillDir "SKILL.md") -Value $skillMd -Encoding UTF8
Write-Host "==> 已安装技能: $skillDir"

Write-Host @"

完成。接下来：
1. 重启 TeleAgent（技能在启动时扫描目录才会被索引）；
2. 在对话框里说「跑完通知我微信」，即可让会话里的 Agent 在任务收尾时自动推送。

快速自检：
    python "$(Join-Path $skillDir 'scripts\notify.py')" "测试" --channel weixin --dry-run
"@
