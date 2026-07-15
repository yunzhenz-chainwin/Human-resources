#requires -RunAsAdministrator

[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [ValidateNotNullOrEmpty()]
    [string]$RemoteAddress = "LocalSubnet"
)

$ErrorActionPreference = "Stop"
$ruleName = "TalentHub-LAN-Web"
$displayName = "TalentHub LAN web access (HR and career site)"

if ($PSCmdlet.ShouldProcess("TCP 5173 and 5174 from $RemoteAddress", "Create Windows Firewall inbound rule")) {
    Get-NetFirewallRule -Name $ruleName -ErrorAction SilentlyContinue |
        Remove-NetFirewallRule

    New-NetFirewallRule `
        -Name $ruleName `
        -DisplayName $displayName `
        -Group "TalentHub LAN" `
        -Direction Inbound `
        -Action Allow `
        -Enabled True `
        -Profile Any `
        -Protocol TCP `
        -LocalPort 5173,5174 `
        -RemoteAddress $RemoteAddress | Out-Null
}

$effectiveRule = Get-NetFirewallRule -PolicyStore ActiveStore -Name $ruleName -ErrorAction SilentlyContinue
if (-not $effectiveRule) {
    Write-Warning "The local rule is not present in ActiveStore. Domain Group Policy may be blocking local firewall rules; ask the domain/network administrator to publish the equivalent inbound rule."
    exit 2
}

$effectiveRule | Select-Object DisplayName, Enabled, Profile, Direction, Action, PolicyStoreSourceType
Get-NetFirewallPortFilter -AssociatedNetFirewallRule $effectiveRule |
    Select-Object Protocol, LocalPort, RemotePort
Get-NetFirewallAddressFilter -AssociatedNetFirewallRule $effectiveRule |
    Select-Object RemoteAddress

Write-Host "[OK] Firewall access is effective for TCP 5173/5174 from $RemoteAddress." -ForegroundColor Green
Write-Host "The backend API remains bound to 127.0.0.1 and is reached through the frontend proxy." -ForegroundColor DarkGray
