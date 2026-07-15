#requires -RunAsAdministrator

[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [switch]$StopServices
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$taskNames = "TalentHub-LAN-Backend", "TalentHub-LAN-HR", "TalentHub-LAN-Career"

foreach ($taskName in $taskNames) {
    if (-not (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue)) {
        Write-Host "[SKIP] $taskName is not installed." -ForegroundColor DarkGray
        continue
    }
    if ($PSCmdlet.ShouldProcess($taskName, "Stop and unregister startup task")) {
        Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
        Write-Host "[OK] Removed $taskName." -ForegroundColor Green
    }
}

if ($StopServices -and $PSCmdlet.ShouldProcess("TalentHub listeners", "Stop verified services")) {
    & (Join-Path $root "stop-dev.ps1")
}
