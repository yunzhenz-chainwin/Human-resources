@echo off
REM Stop verified TalentHub development services only.
powershell -ExecutionPolicy Bypass -NoProfile -File "%~dp0stop-dev.ps1"
echo.
pause
