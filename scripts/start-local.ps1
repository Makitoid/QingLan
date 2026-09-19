#requires -Version 7.0
<#
    青蓝 OJ 本机开发一键启动（PowerShell 7）

    顺序：判题沙箱 go-judge -> 后端 API -> 判题 worker -> 前端
    默认每个常驻服务开一个独立窗口方便看日志；-Headless 则改为后台运行 + 写日志文件。
    全流程幂等：已在运行的跳过，缺依赖的补装。
#>
[CmdletBinding()]
param(
    [switch]$SkipFrontend,
    [switch]$NoReload,
    [switch]$OpenBrowser,
    [switch]$Headless
)

$ErrorActionPreference = 'Stop'
$ProgressPreference    = 'SilentlyContinue'

# ---------- 路径与常量 ----------
$Root        = Split-Path -Parent $PSScriptRoot
$Backend     = Join-Path $Root 'backend'
$Frontend    = Join-Path $Root 'frontend'
$LogDir      = Join-Path $Root 'logs'
$Python      = Join-Path $Backend '.venv\Scripts\python.exe'
$JudgeName   = 'qinglan-judge'
$JudgeImage  = 'qinglan-go-judge:v1.12.3-gcc'
$ComposeFile = Join-Path $Root 'docker\compose.yml'

$ApiUrl   = 'http://127.0.0.1:8000'
$JudgeUrl = 'http://127.0.0.1:5050'

function Write-Step($m) { Write-Host "`n==> $m" -ForegroundColor Cyan }
function Write-Ok($m)   { Write-Host "    [ok] $m" -ForegroundColor Green }
function Write-Skip($m) { Write-Host "    [skip] $m" -ForegroundColor DarkGray }
function Write-Note($m) { Write-Host "    [!] $m" -ForegroundColor Yellow }

# ---------- 工具函数 ----------
function Resolve-Docker {
    if ($c = Get-Command docker -ErrorAction SilentlyContinue) { return $c.Source }
    $p = Join-Path $env:LOCALAPPDATA 'Programs\DockerDesktop\resources\bin\docker.exe'
    if (Test-Path $p) { return $p }
    throw '找不到 docker 可执行文件。请先安装 Docker Desktop 并确保其在运行。'
}

function Test-DockerDaemon($Docker) {
    & $Docker version --format '{{.Server.Version}}' 2>$null | Out-Null
    $LASTEXITCODE -eq 0
}

function Test-PortListening([int]$Port) {
    $null -ne (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
               Select-Object -First 1)
}

# -SkipHttpErrorCheck 是 PowerShell 7 独有，非 2xx 也不抛异常，健康检查因此更简洁
function Test-Http($Url) {
    try {
        $r = Invoke-WebRequest -Uri $Url -SkipHttpErrorCheck -TimeoutSec 3
        $r.StatusCode -ge 200 -and $r.StatusCode -lt 400
    } catch { $false }
}

function Wait-Http($Url, [int]$TimeoutSec = 40) {
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        if (Test-Http $Url) { return $true }
        Start-Sleep -Milliseconds 700
    }
    $false
}

function Start-ServiceProcess($Name, $Command) {
    if ($Headless) {
        $out = Join-Path $LogDir "$Name.out.log"
        $err = Join-Path $LogDir "$Name.err.log"
        Start-Process pwsh -WindowStyle Hidden `
            -ArgumentList @('-NoProfile', '-Command', $Command) `
            -RedirectStandardOutput $out -RedirectStandardError $err
    } else {
        $title = "`$Host.UI.RawUI.WindowTitle='qinglan-$Name'"
        Start-Process pwsh -ArgumentList @('-NoExit', '-NoProfile', '-Command', "$title; $Command")
    }
}

# ---------- 0. 前置检查 ----------
Write-Step '检查环境'
Write-Ok "PowerShell $([System.Environment]::Version) / pwsh 7 运行时"

$Docker = Resolve-Docker
Write-Ok "docker: $Docker"

if (-not (Test-DockerDaemon $Docker)) {
    Write-Note 'Docker 守护进程未运行，尝试启动 Docker Desktop…'
    $dd = @(
        (Join-Path $env:ProgramFiles 'Docker\Docker Desktop.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\DockerDesktop\Docker Desktop.exe')
    ) | Where-Object { Test-Path $_ } | Select-Object -First 1

    if ($dd) {
        Start-Process $dd
        $deadline = (Get-Date).AddSeconds(120)
        while ((Get-Date) -lt $deadline) {
            if (Test-DockerDaemon $Docker) { break }
            Start-Sleep -Seconds 3
        }
    }
    if (-not (Test-DockerDaemon $Docker)) {
        throw 'Docker Desktop 未能就绪。请手动启动它后重试。'
    }
}
Write-Ok 'Docker 守护进程正常'

if (-not (Test-Path $Backend))  { throw "找不到后端目录: $Backend" }
if (-not (Test-Path $Frontend)) { throw "找不到前端目录: $Frontend" }
if ($Headless) { New-Item -ItemType Directory -Path $LogDir -Force | Out-Null }

# ---------- 1. 一次性依赖 ----------
Write-Step '准备依赖'

if (Test-Path $Python) {
    Write-Skip '后端虚拟环境已存在'
} else {
    Write-Host '    创建虚拟环境并安装后端依赖（首次约 1-2 分钟）…'
    $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($pyLauncher) {
        & py -3.14 -m venv (Join-Path $Backend '.venv')
        if ($LASTEXITCODE -ne 0) { & py -3 -m venv (Join-Path $Backend '.venv') }
    } else {
        & python -m venv (Join-Path $Backend '.venv')
    }
    if (-not (Test-Path $Python)) { throw '虚拟环境创建失败' }
    & $Python -m pip install --disable-pip-version-check -r (Join-Path $Backend 'requirements.txt')
    if ($LASTEXITCODE -ne 0) { throw '后端依赖安装失败' }
    Write-Ok '后端依赖已安装'
}

if ($SkipFrontend) {
    Write-Skip '按参数跳过前端'
} elseif (Test-Path (Join-Path $Frontend 'node_modules')) {
    Write-Skip '前端依赖已存在'
} else {
    Write-Host '    安装前端依赖（首次可能需要几分钟）…'
    Push-Location $Frontend
    & npm install
    $npmExit = $LASTEXITCODE
    Pop-Location
    if ($npmExit -ne 0) { throw '前端依赖安装失败' }
    Write-Ok '前端依赖已安装'
}

# ---------- 2. 判题沙箱 ----------
Write-Step '启动判题沙箱 go-judge'

& $Docker image inspect $JudgeImage 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "    镜像 $JudgeImage 不存在，开始构建（首次约 5 分钟）…"
    & $Docker compose -f $ComposeFile build go-judge
    if ($LASTEXITCODE -ne 0) { throw '判题镜像构建失败' }
    Write-Ok '判题镜像已构建'
} else {
    Write-Skip '判题镜像已存在'
}

$running = & $Docker ps -q  -f "name=^$JudgeName`$" 2>$null
$exists  = & $Docker ps -aq -f "name=^$JudgeName`$" 2>$null

if ($running) {
    Write-Skip '沙箱容器已在运行'
} elseif ($exists) {
    & $Docker start $JudgeName | Out-Null
    Write-Ok '已启动既有沙箱容器'
} else {
    # --cgroupns=host 必需：cgroup v2 下缺少它，go-judge 会因 "cgroup path is empty" 启动即崩溃
    & $Docker run -d --name $JudgeName --restart unless-stopped `
        --privileged --cgroupns=host --shm-size=256m `
        -p 5050:5050 $JudgeImage | Out-Null
    if ($LASTEXITCODE -ne 0) { throw '沙箱容器启动失败' }
    Write-Ok '沙箱容器已创建'
}

if (Wait-Http "$JudgeUrl/version" 20) {
    Write-Ok '沙箱健康检查通过 (5050)'
} else {
    Write-Note ("沙箱未响应 5050。查看日志： docker logs --tail 50 {0}" -f $JudgeName)
}

# ---------- 3. 后端 API ----------
Write-Step '启动后端 API (8000)'
if (Test-PortListening 8000) {
    Write-Skip '8000 已有服务，跳过（要重启请先跑 stop-local.ps1）'
} else {
    $uv = "-m uvicorn app.main:app --host 127.0.0.1 --port 8000" + (-not $NoReload ? ' --reload' : '')
    # -u 关闭 python 输出缓冲：否则 -Headless 重定向到文件时日志会卡在块缓冲里不落盘
    Start-ServiceProcess 'backend' "Set-Location '$Backend'; & '$Python' -u $uv"
    if (Wait-Http "$ApiUrl/docs" 45) {
        Write-Ok "后端已就绪: $ApiUrl/docs"
    } else {
        Write-Note $(if ($Headless) { "后端未就绪，看 $LogDir\backend.err.log" } else { '后端未就绪，看 qinglan-backend 窗口' })
    }
}

# ---------- 4. 判题 worker ----------
Write-Step '启动判题 worker'
$worker = Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
          Where-Object { $_.CommandLine -match 'app\.judge\.worker' } | Select-Object -First 1
if ($worker) {
    Write-Skip "worker 已在运行 (PID $($worker.ProcessId))"
} else {
    Start-ServiceProcess 'worker' "Set-Location '$Backend'; & '$Python' -u -m app.judge.worker"
    Start-Sleep -Seconds 2
    Write-Ok 'worker 已启动（该进程不打印日志，无输出属正常）'
}

# ---------- 5. 前端 ----------
$FrontendUrl = 'http://localhost:5173'
if (-not $SkipFrontend) {
    Write-Step '启动前端 (5173)'
    if (Test-PortListening 5173) {
        Write-Skip '5173 已被占用，沿用现有前端实例'
    } else {
        Start-ServiceProcess 'frontend' "Set-Location '$Frontend'; & npm run dev"
        if (Wait-Http 'http://localhost:5173/' 45) {
            Write-Ok "前端已就绪: $FrontendUrl"
        } elseif (Wait-Http 'http://localhost:5174/' 5) {
            $FrontendUrl = 'http://localhost:5174'   # Vite 端口被占时会自动顺延
            Write-Ok "前端改用 $FrontendUrl"
        } else {
            Write-Note $(if ($Headless) { "前端未就绪，看 $LogDir\frontend.out.log" } else { '前端未就绪，看 qinglan-frontend 窗口' })
        }
    }
}

# ---------- 汇总 ----------
Write-Step '启动完成'
$stopHint = if ($Headless) { "日志目录  $LogDir" } else { '各服务在独立窗口中，关窗口即停止' }
Write-Host @"
    前端    $FrontendUrl   (admin / admin123)
    后端    $ApiUrl/docs
    沙箱    $JudgeUrl/version
    数据库  $Backend\data\cg.db
    $stopHint

    停止全部：  scripts\stop-local.ps1
    沙箱日志：  docker logs -f $JudgeName
"@ -ForegroundColor Gray

if ($OpenBrowser) { Start-Process $FrontendUrl }
