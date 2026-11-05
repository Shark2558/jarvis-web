# JARVIS home kit, the Windows half of the setup (R3 D2). Right-click -> Run with PowerShell.
# Safe to run again: every step checks first and skips what is already done.
#Requires -RunAsAdministrator
$ErrorActionPreference = 'Stop'
$Kit = Split-Path -Parent $MyInvocation.MyCommand.Path
$Distro = 'Ubuntu-24.04'

function Say($text) { Write-Host ''; Write-Host "== $text" -ForegroundColor Cyan }
function Ask($text) { return (Read-Host $text) }
function AskSecret($text) { # typed without echo
  $secure = Read-Host $text -AsSecureString
  $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
  try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr) }
  finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
}
function Yes($text) { return ((Read-Host "$text (Y/N)") -match '^[Yy]') }
function InWsl($command) { wsl -d $Distro -- bash -lc $command; if ($LASTEXITCODE -ne 0) { throw 'A step inside Ubuntu failed. Read the lines above and tell Claude.' } }
function WslPath($path) { return (wsl -d $Distro -- wslpath -a ($path -replace '\\', '/')).Trim() }

# 1. Windows and virtualisation -----------------------------------------------------------------
Say 'Checking this laptop'
$build = [Environment]::OSVersion.Version.Build
if ($build -lt 19045) { throw 'Windows 10 needs version 22H2 or newer (or use Windows 11). Run Windows Update first.' }
$virt = (Get-CimInstance Win32_Processor | Select-Object -First 1).VirtualizationFirmwareEnabled
if (-not $virt -and -not (Get-CimInstance Win32_ComputerSystem).HypervisorPresent) {
    throw 'Virtualization is off in the BIOS. Ask Claude for the steps for your laptop, then run this again.'
}
Write-Host 'This laptop can run it.'

# 2. WSL2 and Ubuntu ----------------------------------------------------------------------------
Say 'Installing Ubuntu inside Windows (WSL2)'
$have = (wsl -l -q 2>$null) -join ' ' -replace "`0", ''
if ($have -notmatch [regex]::Escape($Distro)) {
    wsl --install -d $Distro
    Write-Host 'If Windows asks to restart, restart, then run this script again.'
    Write-Host 'When Ubuntu opens the first time, choose a user name and a password and write them down.'
    if (-not (Yes 'Has Ubuntu finished setting up and shown a prompt?')) { exit 0 }
}

# 3. WSL settings -------------------------------------------------------------------------------
$conf = Join-Path $env:UserProfile '.wslconfig'
if (-not (Test-Path $conf)) {
    Copy-Item (Join-Path $Kit 'wslconfig.example') $conf
    Write-Host 'Saved your WSL settings (5 GB of memory; keeps Ubuntu running with no window open).'
} elseif (Yes "You already have $conf. Replace it with the JARVIS settings?") {
    Copy-Item $conf "$conf.old" -Force
    Copy-Item (Join-Path $Kit 'wslconfig.example') $conf -Force
}

# 4. Power --------------------------------------------------------------------------------------
if (Yes 'Keep this laptop awake when it is plugged in, and ignore closing the lid? (The camera alerts stop when the laptop sleeps.)') {
    powercfg /change standby-timeout-ac 0
    powercfg /change hibernate-timeout-ac 0
    powercfg /setacvalueindex SCHEME_CURRENT SUB_BUTTONS LIDACTION 0
    powercfg /setactive SCHEME_CURRENT
    Write-Host 'Done.'
}

# 5. Docker Engine and the kit ------------------------------------------------------------------
Say 'Installing Docker inside Ubuntu'
$kitInWsl = WslPath $Kit
$out = wsl -d $Distro -- bash -lc "KIT_DIR='$kitInWsl' bash '$kitInWsl/setup-wsl.sh' install" | Tee-Object -Variable log
if ($LASTEXITCODE -ne 0) { throw 'Installing Docker failed. Read the lines above and tell Claude.' }
if (($log -join ' ') -match 'RESTART_WSL') { wsl --shutdown; Start-Sleep -Seconds 8 }

# 6. The phone camera and Home Assistant --------------------------------------------------------
Say 'The phone camera (IP Webcam app)'
Write-Host 'On the old phone: open IP Webcam, press Start server, and note the address it shows (like 192.168.1.20).'
$phone = Ask 'Phone address'
$user = Ask 'Camera login'
$pass = AskSecret 'Camera password'
$env:CAMERA_URL = "rtsp://${user}:${pass}@${phone}:8080/h264_ulaw.sdp"
Say 'Home Assistant (optional: press Enter to skip; the camera works without it)'
$env:HA_TOKEN = AskSecret 'Home Assistant token for the JARVIS bridge user'
$env:WSLENV = 'CAMERA_URL:HA_TOKEN'

InWsl "KIT_DIR='$kitInWsl' bash '$kitInWsl/setup-wsl.sh' configure"
InWsl "bash ~/jarvis-home/setup-wsl.sh up"
Remove-Item Env:CAMERA_URL, Env:HA_TOKEN -ErrorAction SilentlyContinue
wsl -d $Distro -- bash -lc 'bash ~/jarvis-home/setup-wsl.sh camera'

# 7. Tailscale Funnel ---------------------------------------------------------------------------
Say 'Making the bridge reachable by JARVIS (Tailscale Funnel, port 8443)'
$ts = Get-Command tailscale -ErrorAction SilentlyContinue
if (-not $ts) { throw 'Tailscale is not installed. Install it from tailscale.com/download, sign in, then run this again.' }
tailscale funnel --bg --https=8443 http://127.0.0.1:8099
$name = ((tailscale status --json | ConvertFrom-Json).Self.DNSName).TrimEnd('.')
$address = "https://${name}:8443"
Write-Host "Your laptop's address for JARVIS: $address"

if (Yes 'Optional: also open Frigate privately on your own phone through Tailscale (only your signed-in devices can see it)?') {
    tailscale serve --bg --https=5443 http://127.0.0.1:8971
    Write-Host "On your phone (Tailscale installed, same account) open https://${name}:5443"
}

# 8. Link ---------------------------------------------------------------------------------------
Say 'Linking to JARVIS'
Write-Host 'In JARVIS: Integrations -> Home -> Link. Type the code it shows.'
$code = Ask 'Link code'
InWsl "bash ~/jarvis-home/setup-wsl.sh link '$code' '$address'"

# 9. Passwords and the logon task ---------------------------------------------------------------
Say 'Write these down'
wsl -d $Distro -- bash -lc 'bash ~/jarvis-home/setup-wsl.sh passwords'
Write-Host 'Frigate: open http://localhost:8971 and log in as admin with the password above.'

Say 'Starting JARVIS Home whenever you log in'
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -WindowStyle Hidden -File `"$Kit\start-home.ps1`""
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:UserName
Register-ScheduledTask -TaskName 'JARVIS Home' -Action $action -Trigger $trigger -Force | Out-Null
Write-Host 'Done. JARVIS should say Online in Integrations -> Home.'
