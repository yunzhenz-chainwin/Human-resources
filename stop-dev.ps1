# Stops only listeners that can be verified as TalentHub development services.

$ErrorActionPreference = "Stop"

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

function Test-TalentHubEndpoint {
    param(
        [Parameter(Mandatory = $true)][string]$Url,
        [Parameter(Mandatory = $true)][string]$ExpectedProcess,
        [Parameter(Mandatory = $true)][int]$ProcessId
    )

    try {
        $process = Get-Process -Id $ProcessId -ErrorAction Stop
        if ($process.ProcessName -ne $ExpectedProcess) {
            return $false
        }
        $response = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 2
        if ($Url -like "*/api/v1/health") {
            return $response.Content -match "talenthub-api"
        }
        return $response.StatusCode -eq 200 -and $response.Content -match '<div id="app"></div>'
    }
    catch {
        return $false
    }
}

$services = @(
    @{ Name = "HR Admin"; Port = 5173; Url = "http://127.0.0.1:5173/"; Process = "node" },
    @{ Name = "Career Site"; Port = 5174; Url = "http://127.0.0.1:5174/"; Process = "node" },
    @{ Name = "Backend API"; Port = 8010; Url = "http://127.0.0.1:8010/api/v1/health"; Process = "python" }
)

foreach ($service in $services) {
    $listenerPid = Get-ListeningProcessId -Port $service.Port
    if (-not $listenerPid) {
        Write-Host "[SKIP] $($service.Name) is not listening on port $($service.Port)." -ForegroundColor DarkGray
        continue
    }

    if (-not (Test-TalentHubEndpoint -Url $service.Url -ExpectedProcess $service.Process -ProcessId $listenerPid)) {
        Write-Host "[SAFE] PID $listenerPid on port $($service.Port) was not verified as TalentHub and was not stopped." -ForegroundColor Yellow
        continue
    }

    Stop-Process -Id $listenerPid -Force
    Write-Host "[STOP] Stopped $($service.Name) (PID $listenerPid)." -ForegroundColor Green
}
