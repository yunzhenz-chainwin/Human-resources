[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("backend", "hr", "career")]
    [string]$Service
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$logDirectory = Join-Path $PSScriptRoot "logs"
New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
$logPath = Join-Path $logDirectory "$Service.log"
$exitCode = 1

# What each service has to be answering before this script considers it up. The task
# repeats on a timer (see install-autostart.ps1), so every fire lands here and has to
# decide whether anything needs starting at all.
#
# The port is probed rather than the process, for two reasons: it is what LAN users
# actually depend on, and it stays true whether the frontend is being served by the dev
# server or by a `vite preview` of the build. The backend also has its body checked, so
# an unrelated listener that grabbed 8010 cannot pass as TalentHub.
$healthProbes = @{
    backend = @{ Url = "http://127.0.0.1:8010/api/v1/health"; Expect = "talenthub-api" }
    hr      = @{ Url = "http://127.0.0.1:5173/"; Expect = "" }
    career  = @{ Url = "http://127.0.0.1:5174/"; Expect = "" }
}

function Test-ServiceHealthy {
    param([Parameter(Mandatory = $true)][hashtable]$Probe)

    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $Probe.Url -TimeoutSec 5
    }
    catch {
        return $false
    }
    if ($response.StatusCode -lt 200 -or $response.StatusCode -ge 400) {
        return $false
    }
    if ($Probe.Expect -and $response.Content -notmatch [regex]::Escape($Probe.Expect)) {
        return $false
    }
    return $true
}

# Deliberately ahead of the transcript: a timer fire that finds the service already
# serving is a no-op, and starting a transcript for each one would push hundreds of
# header blocks a day into the log this file works to keep readable and bounded.
#
# Exiting here is also what makes the timer safe to run against a host where the
# services were started some other way -- by start-dev.ps1, or by hand after an
# incident. Racing a live listener for its port would turn the watchdog into the
# outage it exists to prevent.
if (Test-ServiceHealthy -Probe $healthProbes[$Service]) {
    Write-Host "[$(Get-Date -Format o)] TalentHub service $Service is already serving; nothing to start."
    exit 0
}

# Cap transcript growth under the SYSTEM autostart, which relaunches this script
# on every crash.  When the active log passes the size cap, archive it with a
# timestamp; then prune archives beyond the retention window so the logs folder
# cannot grow without bound across repeated restarts.  Best-effort: a rotation
# failure must never stop the service from starting.
$logSizeCapBytes = 10MB
$logRetentionCount = 10
try {
    if ((Test-Path $logPath) -and ((Get-Item $logPath).Length -ge $logSizeCapBytes)) {
        $stamp = Get-Date -Format "yyyyMMdd-HHmmss-fff"
        Rename-Item -Path $logPath -NewName "$Service.$stamp.log"
    }
    Get-ChildItem -Path $logDirectory -Filter "$Service.*.log" |
        Where-Object { $_.Name -ne "$Service.log" } |
        Sort-Object LastWriteTime -Descending |
        Select-Object -Skip $logRetentionCount |
        Remove-Item -Force
}
catch {
    Write-Warning "Log rotation skipped: $_"
}

try {
    Start-Transcript -Path $logPath -Append | Out-Null
    Write-Host "[$(Get-Date -Format o)] Starting TalentHub service: $Service"

    switch ($Service) {
        "backend" {
            Set-Location (Join-Path $root "backend")
            $python = (Get-Command python.exe -ErrorAction Stop).Source
            & $python -m alembic upgrade head
            if ($LASTEXITCODE -ne 0) {
                throw "Database migration failed with exit code $LASTEXITCODE."
            }
            # run_backend.py enables uvicorn's reloader by default because it is
            # primarily the local dev launcher and a stale process there has cost
            # real debugging time. As a SYSTEM autostart service that default is
            # wrong: the reloader spawns a child process the service manager does
            # not know about, and watches the source tree for the life of the host.
            $env:BACKEND_RELOAD = "0"
            & $python run_backend.py
            $exitCode = $LASTEXITCODE
        }
        "hr" {
            Set-Location (Join-Path $root "frontend")
            $npm = (Get-Command npm.cmd -ErrorAction Stop).Source
            & $npm run build
            if ($LASTEXITCODE -ne 0) {
                throw "Frontend build failed with exit code $LASTEXITCODE."
            }
            & $npm exec -- vite preview --configLoader native --host 0.0.0.0 --port 5173 --strictPort
            $exitCode = $LASTEXITCODE
        }
        "career" {
            Set-Location (Join-Path $root "career-frontend")
            $npm = (Get-Command npm.cmd -ErrorAction Stop).Source
            & $npm run build
            if ($LASTEXITCODE -ne 0) {
                throw "Career frontend build failed with exit code $LASTEXITCODE."
            }
            & $npm exec -- vite preview --configLoader native --host 0.0.0.0 --port 5174 --strictPort
            $exitCode = $LASTEXITCODE
        }
    }

    Write-Host "[$(Get-Date -Format o)] TalentHub service $Service exited with code $exitCode."
}
catch {
    Write-Error $_
    $exitCode = 1
}
finally {
    try { Stop-Transcript | Out-Null } catch { }
}

exit $exitCode
