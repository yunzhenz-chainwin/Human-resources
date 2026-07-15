# TalentHub Windows LAN deployment

## Live status (2026-07-15)

- Database migration: `c83f2a6d4e70` (two-stage interviews), integrity check passed.
- Windows Firewall rule `TalentHub-LAN-Web`: effective for TCP `5173,5174`
  from `10.201.7.0/24`; API `8010` remains loopback-only.
- Startup tasks `TalentHub-LAN-Backend`, `TalentHub-LAN-HR`, and
  `TalentHub-LAN-Career`: installed under `SYSTEM` and running.
- Localhost, computer-name, LAN-IP, frontend API proxy, and both web portals:
  verified HTTP 200 after the final restart.
- Pre-migration backup:
  `backend/talenthub-dev.before-two-stage-20260715-101742.db`.

One test from a manager's actual workstation is still required to confirm that
company DNS, proxy, VLAN, VPN, and endpoint security permit the connection.

This deployment keeps the backend private on loopback and exposes only the two
Vite frontends to the local network. Both frontends proxy `/api` to the backend,
so the manager uses one origin and no direct API port is required.

## Current server addresses

- Computer name: `WIN-K5M743HA9UN`
- Current IPv4: `10.201.7.12/24`
- Network adapter MAC: `BC-24-11-36-D5-EF`
- HR and manager portal: `http://WIN-K5M743HA9UN:5173/`
- Career site: `http://WIN-K5M743HA9UN:5174/`
- IP fallbacks: `http://10.201.7.12:5173/` and `http://10.201.7.12:5174/`

Prefer the computer-name URL. If company DNS does not resolve that name, ask IT
to reserve `10.201.7.12` for the MAC address above, or create an internal DNS
record such as `talenthub`. For a custom DNS name, add it to
`VITE_ALLOWED_HOSTS` in each frontend's `.env.local` file and restart the two
frontends, for example:

```text
VITE_ALLOWED_HOSTS=talenthub,talenthub.company.local
```

## Firewall (administrator and possibly domain IT required)

The active network is currently using the Windows **Public** profile with
inbound traffic blocked. Run an elevated PowerShell from the repository root:

```powershell
.\deploy\windows-lan\install-firewall.ps1 -RemoteAddress "10.201.7.0/24"
```

The rule opens only TCP `5173` and `5174`, and only to the specified LAN. Port
`8010` remains loopback-only. Do not replace the subnet with `Any`; that would
unnecessarily expose the login and candidate data to every reachable network.

This server reports `LocalFirewallRules: N/A (GPO-store only)`. Therefore, a
locally created rule may be rejected or omitted from the effective policy. If
the script exits with code 2, the domain/network administrator must publish the
same inbound allow rule through Group Policy:

- Protocol: TCP
- Local ports: `5173,5174`
- Remote address: `10.201.7.0/24`
- Profiles: the server's active profile (currently Public), or all profiles
- Direction/action: inbound/allow

## Automatic restart after Windows reboot

The current hidden development processes do not survive a reboot and are not
automatically restarted after a crash. Install three startup tasks from an
elevated PowerShell:

```powershell
.\deploy\windows-lan\install-autostart.ps1
```

This does not interrupt the currently running services. It takes effect at the
next Windows startup. To transition immediately with a brief controlled outage:

```powershell
.\deploy\windows-lan\install-autostart.ps1 -StartNow
```

The tasks run as `SYSTEM`, start at boot, and retry up to 100 times at one-minute
intervals if a process exits. Logs are stored under
`deploy/windows-lan/logs/`. Remove the tasks without deleting application data:

```powershell
.\deploy\windows-lan\uninstall-autostart.ps1 -StopServices
```

## Verification

Run the non-mutating check locally:

```powershell
.\deploy\windows-lan\test-deployment.ps1
```

Then test the HR URL from the manager's computer. That remote test is required
because a local request to the server's own LAN IP cannot prove that Windows
Firewall, VLAN isolation, or upstream network ACLs permit another device.

## Security boundary

These are plain HTTP development endpoints intended only for a trusted internal
LAN. Never port-forward `5173`, `5174`, or `8010` to the Internet. Before remote
or cross-site use, put the built frontends and API behind an HTTPS reverse proxy
with a company-managed certificate and backup/monitoring controls.
