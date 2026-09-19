@echo off
rem Qinglan OJ - one-click start. Requires PowerShell 7 (pwsh).
where pwsh >nul 2>nul
if errorlevel 1 (
  echo [ERROR] PowerShell 7 ^(pwsh^) not found on PATH.
  echo         Install it with:  winget install Microsoft.PowerShell
  echo.
  pause
  exit /b 1
)
pwsh -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-local.ps1" %*
echo.
pause
