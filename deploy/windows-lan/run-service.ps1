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
