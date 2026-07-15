[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Net.Http
$computerName = [System.Net.Dns]::GetHostName()
$lanAddress = [System.Net.Dns]::GetHostAddresses($computerName) |
    Where-Object {
        $_.AddressFamily -eq [System.Net.Sockets.AddressFamily]::InterNetwork -and
        -not [System.Net.IPAddress]::IsLoopback($_)
    } |
    Select-Object -First 1 |
    ForEach-Object { $_.IPAddressToString }

function Test-Endpoint {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Url,
        [string]$ExpectedText = ""
    )

    $handler = [System.Net.Http.HttpClientHandler]::new()
    $handler.UseProxy = $false
    $client = [System.Net.Http.HttpClient]::new($handler)
    $client.Timeout = [TimeSpan]::FromSeconds(5)
    try {
        $response = $client.GetAsync($Url).GetAwaiter().GetResult()
        if (-not $response.IsSuccessStatusCode) {
            throw "HTTP $([int]$response.StatusCode)"
        }
        $content = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
        if ($ExpectedText -and $content -notmatch [regex]::Escape($ExpectedText)) {
            throw "Response did not contain '$ExpectedText'."
        }
        Write-Host ("[PASS] {0,-24} {1}" -f $Name, $Url) -ForegroundColor Green
        return $true
    }
    catch {
        Write-Host ("[FAIL] {0,-24} {1} - {2}" -f $Name, $Url, $_.Exception.Message) -ForegroundColor Red
        return $false
    }
    finally {
        $client.Dispose()
        $handler.Dispose()
    }
}

$results = @(
    Test-Endpoint -Name "Backend loopback" -Url "http://127.0.0.1:8010/api/v1/health" -ExpectedText "talenthub-api"
    Test-Endpoint -Name "HR localhost" -Url "http://127.0.0.1:5173/" -ExpectedText '<div id="app"></div>'
    Test-Endpoint -Name "HR API proxy" -Url "http://127.0.0.1:5173/api/v1/health" -ExpectedText "talenthub-api"
    Test-Endpoint -Name "Career localhost" -Url "http://127.0.0.1:5174/" -ExpectedText '<div id="app"></div>'
    Test-Endpoint -Name "Career API proxy" -Url "http://127.0.0.1:5174/api/v1/health" -ExpectedText "talenthub-api"
    Test-Endpoint -Name "HR computer name" -Url "http://${computerName}:5173/" -ExpectedText '<div id="app"></div>'
    Test-Endpoint -Name "Career computer name" -Url "http://${computerName}:5174/" -ExpectedText '<div id="app"></div>'
)

if ($lanAddress) {
    $results += Test-Endpoint -Name "HR LAN address" -Url "http://${lanAddress}:5173/" -ExpectedText '<div id="app"></div>'
    $results += Test-Endpoint -Name "HR LAN API proxy" -Url "http://${lanAddress}:5173/api/v1/health" -ExpectedText "talenthub-api"
    $results += Test-Endpoint -Name "Career LAN address" -Url "http://${lanAddress}:5174/" -ExpectedText '<div id="app"></div>'
}

Write-Host ""
Write-Host "Listener bindings:" -ForegroundColor Cyan
netstat -ano -p tcp |
    Select-String -Pattern '^\s*TCP\s+(0\.0\.0\.0:5173|0\.0\.0\.0:5174|127\.0\.0\.1:8010)\s+.*LISTENING'

Write-Host ""
Write-Host "Preferred manager URL: http://${computerName}:5173/" -ForegroundColor Cyan
if ($lanAddress) {
    Write-Host "IP fallback URL:        http://${lanAddress}:5173/" -ForegroundColor Cyan
}
Write-Host "A successful local LAN-address probe does not prove that Windows Firewall or upstream network policy permits another computer. Test once from the manager's device." -ForegroundColor Yellow

if ($results -contains $false) {
    exit 1
}
