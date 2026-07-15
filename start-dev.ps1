# TalentHub local development launcher.
# Repeated runs skip healthy services instead of producing port conflicts.

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot

function Test-HttpEndpoint {
    param(
        [Parameter(Mandatory = $true)][string]$Url,
        [string]$ExpectedText = ""
    )

    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 2
        if ($response.StatusCode -lt 200 -or $response.StatusCode -ge 400) {
            return $false
        }
        if ($ExpectedText -and $response.Content -notmatch [regex]::Escape($ExpectedText)) {
            return $false
        }
        return $true
    }
    catch {
        return $false
    }
}

function Get-ListeningProcessId {
    param([Parameter(Mandatory = $true)][int]$Port)

    $line = netstat -ano -p tcp |
        Select-String -Pattern "^\s*TCP\s+\S+:$Port\s+\S+\s+LISTENING\s+(\d+)\s*$" |
        Select-Object -First 1
    if (-not $line) {
        return $null
    }
    return [int]$line.Matches[0].Groups[1].Value
}

function Get-LanIPv4Address {
    try {
        return [System.Net.Dns]::GetHostAddresses([System.Net.Dns]::GetHostName()) |
            Where-Object {
                $_.AddressFamily -eq [System.Net.Sockets.AddressFamily]::InterNetwork -and
                -not [System.Net.IPAddress]::IsLoopback($_)
            } |
            Select-Object -First 1 |
            ForEach-Object { $_.IPAddressToString }
    }
    catch {
        return $null
    }
}

function Start-TalentHubService {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][int]$Port,
        [Parameter(Mandatory = $true)][string]$HealthUrl,
        [string]$ExpectedText = "",
        [Parameter(Mandatory = $true)][string]$WorkingDirectory,
        [Parameter(Mandatory = $true)][string]$Command
    )

    if (Test-HttpEndpoint -Url $HealthUrl -ExpectedText $ExpectedText) {
        Write-Host "[OK] $Name is already healthy on port $Port. Skipping duplicate start." -ForegroundColor Green
        return
    }

    $listenerPid = Get-ListeningProcessId -Port $Port
    if ($listenerPid) {
        Write-Host "[WARN] Port $Port for $Name is held by PID $listenerPid, but its health check failed." -ForegroundColor Yellow
        Write-Host "       Run restart-dev.bat, or run stop-dev.bat before starting again." -ForegroundColor Yellow
        return
    }

    $windowCommand = "`$host.UI.RawUI.WindowTitle = '$Name'; $Command"
    Start-Process powershell.exe -WorkingDirectory $WorkingDirectory -WindowStyle Hidden -ArgumentList @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-Command", $windowCommand
    ) | Out-Null
    Write-Host "[START] Starting $Name..." -ForegroundColor Cyan
}

Write-Host "TalentHub development environment check" -ForegroundColor Cyan

Start-TalentHubService `
    -Name "TalentHub Backend API" `
    -Port 8010 `
    -HealthUrl "http://127.0.0.1:8010/api/v1/health" `
    -ExpectedText "talenthub-api" `
    -WorkingDirectory (Join-Path $root "backend") `
    -Command "python run_backend.py"

Start-TalentHubService `
    -Name "TalentHub HR Admin" `
    -Port 5173 `
    -HealthUrl "http://127.0.0.1:5173/src/main.ts" `
    -WorkingDirectory (Join-Path $root "frontend") `
    -Command "npm run dev"

Start-TalentHubService `
    -Name "TalentHub Career Site" `
    -Port 5174 `
    -HealthUrl "http://127.0.0.1:5174/src/main.ts" `
    -WorkingDirectory (Join-Path $root "career-frontend") `
    -Command "npm run dev"

for ($attempt = 1; $attempt -le 15; $attempt++) {
    $apiReady = Test-HttpEndpoint -Url "http://127.0.0.1:8010/api/v1/health" -ExpectedText "talenthub-api"
    $hrReady = Test-HttpEndpoint -Url "http://127.0.0.1:5173/src/main.ts"
    $careerReady = Test-HttpEndpoint -Url "http://127.0.0.1:5174/src/main.ts"
    if ($apiReady -and $hrReady -and $careerReady) {
        break
    }
    Start-Sleep -Seconds 1
}

Write-Host ""
Write-Host "Service status:" -ForegroundColor Cyan
$checks = @(
    @{ Name = "HR Admin"; Url = "http://127.0.0.1:5173/"; Probe = "http://127.0.0.1:5173/src/main.ts"; Expected = "" },
    @{ Name = "Career Site"; Url = "http://127.0.0.1:5174/"; Probe = "http://127.0.0.1:5174/src/main.ts"; Expected = "" },
    @{ Name = "Backend API"; Url = "http://127.0.0.1:8010/api/v1/health"; Probe = "http://127.0.0.1:8010/api/v1/health"; Expected = "talenthub-api" }
)
foreach ($check in $checks) {
    $ready = Test-HttpEndpoint -Url $check.Probe -ExpectedText $check.Expected
    $label = if ($ready) { "READY" } else { "NOT READY" }
    $color = if ($ready) { "Green" } else { "Red" }
    Write-Host ("  {0,-12} {1,-10} {2}" -f $check.Name, $label, $check.Url) -ForegroundColor $color
}

Write-Host ""
Write-Host "Use restart-dev.bat for a clean restart." -ForegroundColor Yellow
Write-Host "Use stop-dev.bat to stop the three verified TalentHub services." -ForegroundColor DarkGray

$computerName = [System.Net.Dns]::GetHostName()
$lanAddress = Get-LanIPv4Address
Write-Host ""
Write-Host "Manager LAN URLs (Windows Firewall must allow TCP 5173/5174):" -ForegroundColor Cyan
Write-Host "  HR / manager: http://${computerName}:5173/" -ForegroundColor Green
Write-Host "  Career site:  http://${computerName}:5174/" -ForegroundColor Green
if ($lanAddress) {
    Write-Host "  IP fallback:  http://${lanAddress}:5173/ and http://${lanAddress}:5174/" -ForegroundColor DarkGray
}
Write-Host "Do not expose these HTTP development ports directly to the public Internet." -ForegroundColor Yellow
