#requires -RunAsAdministrator

[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [switch]$StartNow
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$runner = (Resolve-Path (Join-Path $PSScriptRoot "run-service.ps1")).Path
$powerShell = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"

# Fail before changing Task Scheduler if the machine cannot run the services.
Get-Command python.exe -ErrorAction Stop | Out-Null
Get-Command npm.cmd -ErrorAction Stop | Out-Null

$principal = New-ScheduledTaskPrincipal `
    -UserId "SYSTEM" `
    -LogonType ServiceAccount `
    -RunLevel Highest
$trigger = New-ScheduledTaskTrigger -AtStartup
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -RestartCount 100 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -MultipleInstances IgnoreNew `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

$tasks = @(
    @{ Name = "TalentHub-LAN-Backend"; Service = "backend" },
    @{ Name = "TalentHub-LAN-HR"; Service = "hr" },
    @{ Name = "TalentHub-LAN-Career"; Service = "career" }
)

foreach ($task in $tasks) {
    $arguments = '-NoProfile -ExecutionPolicy Bypass -File "{0}" -Service {1}' -f $runner, $task.Service
    $action = New-ScheduledTaskAction `
        -Execute $powerShell `
        -Argument $arguments `
        -WorkingDirectory $root

    if ($PSCmdlet.ShouldProcess($task.Name, "Register persistent TalentHub startup task")) {
        Register-ScheduledTask `
            -TaskName $task.Name `
            -Action $action `
            -Trigger $trigger `
            -Principal $principal `
            -Settings $settings `
            -Description "Keep the TalentHub $($task.Service) service available after Windows restarts." `
            -Force | Out-Null
        Write-Host "[OK] Registered $($task.Name)." -ForegroundColor Green
    }
}

if ($StartNow -and $PSCmdlet.ShouldProcess("TalentHub services", "Replace current verified development listeners with scheduled services")) {
    & (Join-Path $root "stop-dev.ps1")
    # stop-dev terminates the child listeners. Explicitly end any still-running
    # task wrapper before starting it again; MultipleInstances=IgnoreNew would
    # otherwise discard the immediate restart request.
    foreach ($task in $tasks) {
        Stop-ScheduledTask -TaskName $task.Name -ErrorAction SilentlyContinue
    }
    for ($attempt = 1; $attempt -le 30; $attempt++) {
        $running = @(
            $tasks | Where-Object {
                (Get-ScheduledTask -TaskName $_.Name -ErrorAction Stop).State -eq "Running"
            }
        )
        if ($running.Count -eq 0) {
            break
        }
        Start-Sleep -Seconds 1
    }
    foreach ($task in $tasks) {
        Start-ScheduledTask -TaskName $task.Name
    }
    Write-Host "[START] Scheduled TalentHub services are starting. Allow up to one minute." -ForegroundColor Cyan
}
else {
    Write-Host "Tasks will start automatically at the next Windows startup." -ForegroundColor Cyan
    Write-Host "Use -StartNow for a controlled transition from the currently running services." -ForegroundColor DarkGray
}
