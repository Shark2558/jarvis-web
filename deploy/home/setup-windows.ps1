# JARVIS home kit, the Windows half of the setup (R3 D2). Open PowerShell as administrator, then:
#   cd C:\JARVIS-Home
#   powershell -ExecutionPolicy Bypass -File .\setup-windows.ps1
# Later, once Home Assistant runs and has its accounts (optional):
#   powershell -ExecutionPolicy Bypass -File .\setup-windows.ps1 -HaToken
# Later, when JARVIS says the home kit is older than JARVIS (download it again, extract it over
# this folder, then):
#   powershell -ExecutionPolicy Bypass -File .\setup-windows.ps1 -Update
# Later, optional: the photo folder the laptop may read to find faces, or switching that off:
#   powershell -ExecutionPolicy Bypass -File .\setup-windows.ps1 -PhotosDir "C:\Users\you\Pictures\JARVIS"
#   powershell -ExecutionPolicy Bypass -File .\setup-windows.ps1 -PhotosDir off
# Later, when the home camera for the desk coaches is set up in its own app (R8), or to stop that:
#   powershell -ExecutionPolicy Bypass -File .\setup-windows.ps1 -HomeCamera
#   powershell -ExecutionPolicy Bypass -File .\setup-windows.ps1 -HomeCamera -Off
# Safe to run again: every step checks first and skips what is already done.
param([switch]$HaToken, [switch]$Update, [string]$PhotosDir, [switch]$HomeCamera, [switch]$Off)
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

# 0. Administrator (a right-click on the script does not give it) ------------------------------
$me = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $me.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host 'This needs PowerShell as administrator: Start -> type PowerShell -> Run as administrator. Then type:'
    Write-Host "  cd `"$Kit`""
    if ($HaToken) { Write-Host '  powershell -ExecutionPolicy Bypass -File .\setup-windows.ps1 -HaToken' }
    elseif ($Update) { Write-Host '  powershell -ExecutionPolicy Bypass -File .\setup-windows.ps1 -Update' }
    elseif ($HomeCamera) { Write-Host '  powershell -ExecutionPolicy Bypass -File .\setup-windows.ps1 -HomeCamera' }
    elseif ($PhotosDir) { Write-Host "  powershell -ExecutionPolicy Bypass -File .\setup-windows.ps1 -PhotosDir `"$PhotosDir`"" }
    else { Write-Host '  powershell -ExecutionPolicy Bypass -File .\setup-windows.ps1' }
    exit 1
}

# Later, optional: the Home Assistant token, once Home Assistant runs and has its accounts --------
if ($HaToken) {
    Say 'Home Assistant token for the JARVIS bridge user'
    Write-Host 'Make it at http://localhost:8123 (logged in as the JARVIS bridge person): Profile -> Security -> Long-lived access tokens -> Create.'
    $env:HA_TOKEN = AskSecret 'Paste the token'
    if (-not $env:HA_TOKEN) { Write-Host 'No token: nothing changed.'; exit 0 }
    $env:WSLENV = 'HA_TOKEN'
    try { InWsl 'bash ~/jarvis-home/setup-wsl.sh ha-token' }
    finally { Remove-Item Env:HA_TOKEN -ErrorAction SilentlyContinue }
    exit 0
}

# Later: a newer kit was extracted over this folder. Your settings, passwords and link are kept ----
if ($Update) {
    Say 'Updating JARVIS Home (your camera, passwords, Home Assistant token and link are kept)'
    $kitInWsl = WslPath $Kit
    if ($kitInWsl.Contains("'")) { Write-Host 'The kit folder''s name has a quote mark in it. Extract the kit to C:\ (C:\JARVIS-Home) and run this again.'; exit 1 }
    $env:KIT_DIR = $kitInWsl
    $savedWslEnv = $env:WSLENV
    $env:WSLENV = 'KIT_DIR'
    try { InWsl 'bash "$KIT_DIR/setup-wsl.sh" update' }
    finally { $env:WSLENV = $savedWslEnv; Remove-Item Env:KIT_DIR -ErrorAction SilentlyContinue }
    exit 0
}

# Later, optional (R8): the home camera the desk coaches look through, on this laptop only --------
if ($HomeCamera) {
    $env:HOME_CAMERA_URL = 'off'
    $env:HOME_CAMERA_ID = ''
    if (-not $Off) {
        Say 'The home camera for the desk coaches'
        Write-Host 'Its pictures are looked at on this laptop only. Its address and password stay in bridge.env here.'
        $addr = (Ask 'The camera''s sub-stream address (rtsp://192.168.x.x:554/..., from JARVIS -> Camera -> Cameras -> Check a camera)').Trim()
        if (-not $addr.StartsWith('rtsp://')) { Write-Host 'The address starts with rtsp:// - nothing changed.'; exit 1 }
        $user = (Ask 'The camera''s user name (often admin)').Trim()
        $pass = AskSecret 'The camera''s password (some cameras print it on their label)'
        $id = (Ask 'The camera''s id in JARVIS -> Camera -> Cameras (for example desk_camera)').Trim()
        $env:HOME_CAMERA_URL = 'rtsp://' + [Uri]::EscapeDataString($user) + ':' + [Uri]::EscapeDataString($pass) + '@' + $addr.Substring(7)
        $env:HOME_CAMERA_ID = $id
    }
    $savedWslEnv = $env:WSLENV
    $env:WSLENV = 'HOME_CAMERA_URL:HOME_CAMERA_ID'
    try { InWsl 'bash ~/jarvis-home/setup-wsl.sh home-camera' }
    finally { $env:WSLENV = $savedWslEnv; Remove-Item Env:HOME_CAMERA_URL, Env:HOME_CAMERA_ID -ErrorAction SilentlyContinue }
    exit 0
}

# Later, optional: the photo folder the bridge may READ to find faces (-PhotosDir off stops it) ---
if ($PhotosDir) {
    if ($PhotosDir -eq 'off') {
        InWsl 'bash ~/jarvis-home/setup-wsl.sh photos-dir off'
        exit 0
    }
    if (-not (Test-Path -LiteralPath $PhotosDir -PathType Container)) {
        Write-Host "There is no folder $PhotosDir"
        Write-Host 'In File Explorer: hold Shift, right-click the folder, choose "Copy as path", and paste it after -PhotosDir.'
        exit 1
    }
    Say 'The photo folder'
    Write-Host 'The bridge will only READ the photos in this folder to find faces. It never changes, moves or deletes them, and nothing leaves this laptop.'
    $env:JARVIS_PHOTOS_DIR = WslPath $PhotosDir
    $savedWslEnv = $env:WSLENV
    $env:WSLENV = 'JARVIS_PHOTOS_DIR'
    try { InWsl 'bash ~/jarvis-home/setup-wsl.sh photos-dir' }
    finally { $env:WSLENV = $savedWslEnv; Remove-Item Env:JARVIS_PHOTOS_DIR -ErrorAction SilentlyContinue }
    Write-Host 'To switch it off later:  powershell -ExecutionPolicy Bypass -File .\setup-windows.ps1 -PhotosDir off'
    exit 0
}

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

# 6. The phone camera (Home Assistant's token comes later: -HaToken) ----------------------------
Say 'The phone camera (IP Webcam app)'
Write-Host 'On the old phone: open IP Webcam, press Start server, and note the address it shows (like 192.168.1.20).'
$phone = Ask 'Phone address'
$user = Ask 'Camera login'
$pass = AskSecret 'Camera password'
$env:CAMERA_URL = "rtsp://${user}:${pass}@${phone}:8080/h264_ulaw.sdp"
$env:WSLENV = 'CAMERA_URL'

InWsl "KIT_DIR='$kitInWsl' bash '$kitInWsl/setup-wsl.sh' configure"
InWsl "bash ~/jarvis-home/setup-wsl.sh up"
Remove-Item Env:CAMERA_URL -ErrorAction SilentlyContinue
wsl -d $Distro -- bash -lc 'bash ~/jarvis-home/setup-wsl.sh camera'

# 7. Tailscale Funnel ---------------------------------------------------------------------------
Say 'Making the bridge reachable by JARVIS (Tailscale Funnel, port 8443)'
$ts = Get-Command tailscale -ErrorAction SilentlyContinue
if (-not $ts) { throw 'Tailscale is not installed. Install it from tailscale.com/download, sign in, then run this again.' }
# One door each: the bridge 8443, the offline brain 443, the laptop speech kit 10000. Never take
# over 8443 while it serves something else (R5.2 review: the brain's script once took it).
function Test-FunnelTaken([int]$port, [string]$mine) {
    try { $cfg = (& tailscale funnel status --json 2>$null | Out-String) | ConvertFrom-Json } catch { return $false }
    if (-not $cfg -or -not $cfg.Web) { return $false }
    foreach ($site in $cfg.Web.PSObject.Properties) {
        if ($site.Name -like "*:$port") {
            $targets = @($site.Value.Handlers.PSObject.Properties | ForEach-Object { $_.Value.Proxy })
            if ($targets -notcontains $mine) { return $true }
        }
    }
    return $false
}
if (Test-FunnelTaken 8443 'http://127.0.0.1:8099') {
    throw "Tailscale Funnel's port 8443 already serves something else on this laptop (the offline brain keeps 443, the speech kit 10000; 8443 is the bridge's). See what uses it with: tailscale funnel status, stop it, then run this again."
}
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
# -ExecutionPolicy Bypass: Windows' default policy would block the script after a restart
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$Kit\start-home.ps1`""
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:UserName
Register-ScheduledTask -TaskName 'JARVIS Home' -Action $action -Trigger $trigger -Force | Out-Null
Write-Host 'Done. JARVIS should say Online in Integrations -> Home.'

Say 'Later (optional): Home Assistant'
Write-Host 'Open http://localhost:8123, create your account, add a person "JARVIS bridge" who can log in and is NOT an administrator, make a long-lived token as that person, then run (PowerShell as administrator, in this folder):'
Write-Host '  powershell -ExecutionPolicy Bypass -File .\setup-windows.ps1 -HaToken'
