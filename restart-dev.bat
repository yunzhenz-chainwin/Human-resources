@echo off
REM Safely stop and restart the TalentHub local development environment.
powershell -ExecutionPolicy Bypass -NoProfile -File "%~dp0stop-dev.ps1"
powershell -ExecutionPolicy Bypass -NoProfile -File "%~dp0start-dev.ps1"
echo.
pause
