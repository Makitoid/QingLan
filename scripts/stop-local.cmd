@echo off
rem Qinglan OJ - one-click stop. Requires PowerShell 7 (pwsh).
where pwsh >nul 2>nul
if errorlevel 1 (
  echo [ERROR] PowerShell 7 ^(pwsh^) not found on PATH.
  echo.
  pause
  exit /b 1
)
pwsh -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop-local.ps1" %*
echo.
pause
