#requires -Version 7.0
<#
    青蓝 OJ 本机开发一键停止（PowerShell 7）

    只终止本项目启动的 worker / 后端 / 前端，按命令行特征匹配，不会误伤其它 python 或 node。
#>
[CmdletBinding()]
param(
    [switch]$KeepJudge,
    [switch]$KeepLogs
)

$ErrorActionPreference = 'Continue'

$Root      = Split-Path -Parent $PSScriptRoot
$Frontend  = Join-Path $Root 'frontend'
$LogDir    = Join-Path $Root 'logs'
$JudgeName = 'qinglan-judge'

function Write-Step($m) { Write-Host "`n==> $m" -ForegroundColor Cyan }
function Write-Ok($m)   { Write-Host "    [stop] $m" -ForegroundColor Green }
function Write-Skip($m) { Write-Host "    [skip] $m" -ForegroundColor DarkGray }

function Resolve-Docker {
    if ($c = Get-Command docker -ErrorAction SilentlyContinue) { return $c.Source }
    $p = Join-Path $env:LOCALAPPDATA 'Programs\DockerDesktop\resources\bin\docker.exe'
    if (Test-Path $p) { return $p }
    $null
}

function Stop-ByCommandLine($Pattern, $Label) {
    # 同时匹配 pwsh 包装进程，避免 -Headless 模式留下空的隐藏宿主
    $procs = Get-CimInstance Win32_Process `
        -Filter "Name='python.exe' OR Name='node.exe' OR Name='pwsh.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match $Pattern }

    if (-not $procs) { Write-Skip "$Label 未在运行"; return }
    foreach ($p in $procs) {
        Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
        Write-Ok "$Label (PID $($p.ProcessId))"
    }
}

# ---------- 1. worker ----------
Write-Step '停止判题 worker'
Stop-ByCommandLine 'app\.judge\.worker' 'worker'

# ---------- 2. 后端 ----------
Write-Step '停止后端 API'
Stop-ByCommandLine 'uvicorn\s+app\.main:app' 'backend'

# ---------- 3. 前端（用项目路径限定，避免关掉机器上其它 vite） ----------
Write-Step '停止前端'
Stop-ByCommandLine "vite|$([regex]::Escape($Frontend))" 'frontend'

# ---------- 4. 判题沙箱 ----------
if ($KeepJudge) {
    Write-Step '按参数保留判题沙箱容器'
} else {
    Write-Step '停止判题沙箱 go-judge'
    $docker = Resolve-Docker
    if (-not $docker) {
        Write-Skip '未找到 docker，请手动停止容器'
    } else {
        $ids = & $docker ps -aq -f "name=^$JudgeName`$" 2>$null
        if ($ids) {
            & $docker rm -f $ids 2>$null | Out-Null
            Write-Ok "容器 $JudgeName 已移除"
        } else {
            Write-Skip "容器 $JudgeName 不存在"
        }
    }
}

# ---------- 5. 日志 ----------
if ($KeepLogs) {
    Write-Step '按参数保留日志目录'
} elseif (Test-Path $LogDir) {
    Write-Step '清理 -Headless 日志'
    Remove-Item $LogDir -Recurse -Force -ErrorAction SilentlyContinue
    Write-Ok "已删除 $LogDir"
}

Write-Step '停止完成'
Write-Host '    重新启动： scripts\start-local.ps1' -ForegroundColor Gray
