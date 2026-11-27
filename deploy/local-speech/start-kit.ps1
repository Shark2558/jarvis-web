# deploy/local-speech/start-kit.ps1 -- R5.2 "Your voice": starts the laptop speech kit (Windows,
# plan D1). Runs the kit's speech server (127.0.0.1:11437), the gate in front of it (Caddy,
# 127.0.0.1:11436, checks the key) and publishes the gate with Tailscale Funnel on https port 8443,
# then prints the address and key to give JARVIS. Leave this window open; Ctrl+C or closing it
# stops the kit and closes Funnel on that port. The key is made on the first run and kept in the
# kit's private folder.
#
#   powershell -ExecutionPolicy Bypass -File .\start-kit.ps1             start
#   powershell -ExecutionPolicy Bypass -File .\start-kit.ps1 -SelfTest   start, then the self-test
#   powershell -ExecutionPolicy Bypass -File .\start-kit.ps1 -HttpsPort 10000
#       if the offline brain (deploy/local-brain) already uses Funnel's port 8443 on this laptop
param(
    [ValidateSet(443, 8443, 10000)][int]$HttpsPort = 8443,
    [switch]$SelfTest
)
$ErrorActionPreference = 'Stop'

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$dir = if ($env:JARVIS_SPEECH_KIT_DIR) { $env:JARVIS_SPEECH_KIT_DIR } else { Join-Path $env:LOCALAPPDATA 'JARVIS\LocalSpeech' }
$py = Join-Path $dir 'venv\Scripts\python.exe'
$keyFile = Join-Path $dir 'key'
$gatePort = 11436
$serverPort = 11437

function Need([string]$name, [string]$hint) {
    if (-not (Get-Command $name -ErrorAction SilentlyContinue)) {
        Write-Host "Missing: $name. $hint"
        exit 1
    }
}
Need 'caddy' 'Install it with: winget install CaddyServer.Caddy (or run install-kit.ps1 again).'
Need 'tailscale' 'Install it from https://tailscale.com/download and sign in.'
if (-not (Test-Path -LiteralPath $py)) {
    Write-Host 'The kit is not installed yet: run install-kit.ps1 first (README step 2).'
    exit 1
}

function Test-Port([int]$port) {
    $probe = New-Object System.Net.Sockets.TcpClient
    try { $probe.Connect('127.0.0.1', $port); return $true }
    catch [System.Net.Sockets.SocketException] { return $false }
    finally { $probe.Dispose() }
}

# Refuse to start twice: a second run would fight the first over the ports, and its exit would
# close the first run's Funnel.
foreach ($port in @($gatePort, $serverPort)) {
    if (Test-Port $port) {
        Write-Host "Port $port is already in use, probably by a kit that is already running. Close that window (or stop whatever uses the port), then run this again."
        exit 1
    }
}

# Never take over a Funnel port that already serves something else (the offline brain uses 8443).
function Test-FunnelTaken([int]$port) {
    try { $cfg = (& tailscale funnel status --json 2>$null | Out-String) | ConvertFrom-Json } catch { return $false }
    if (-not $cfg -or -not $cfg.Web) { return $false }
    foreach ($site in $cfg.Web.PSObject.Properties) {
        if ($site.Name -like "*:$port") {
            $targets = @($site.Value.Handlers.PSObject.Properties | ForEach-Object { $_.Value.Proxy })
            if ($targets -notcontains "http://127.0.0.1:$gatePort") { return $true }
        }
    }
    return $false
}
if (Test-FunnelTaken $HttpsPort) {
    Write-Host "Tailscale Funnel's port $HttpsPort already serves something else on this laptop (the offline brain uses 8443). Run this again with -HttpsPort 10000 (or 443), and give JARVIS that address."
    exit 1
}

New-Item -ItemType Directory -Force -Path $dir | Out-Null
# only you (and no inherited group) can read the folder and the key: lock it BEFORE the key exists
& icacls $dir /inheritance:r /grant:r "$($env:USERNAME):(OI)(CI)F" | Out-Null
if (-not (Test-Path -LiteralPath $keyFile) -or (Get-Item -LiteralPath $keyFile).Length -eq 0) {
    # 32 random bytes, base64url, no padding (43 characters)
    $bytes = New-Object byte[] 32
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    $new = [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')
    [System.IO.File]::WriteAllText($keyFile, $new)
}
$key = (Get-Content -Raw -LiteralPath $keyFile).Trim()
if ($key.Length -lt 32) {
    Write-Host "The key file in the kit's folder is too short (it needs 32+ characters). Delete the file named key there and run this again to make a new key (then give JARVIS the new key)."
    exit 1
}

$server = $null
$caddy = $null
$funnelOn = $false
try {
    # The key goes to the server and to Caddy through their environment only (never on a command line).
    $env:JARVIS_LOCAL_SPEECH_KEY = $key
    $env:JARVIS_SPEECH_KIT_DIR = $dir
    $env:JARVIS_SPEECH_KIT_MANIFEST = Join-Path $here 'models.json'
    $server = Start-Process -FilePath $py -ArgumentList @('-I', '-m', 'jarvis.localspeech', 'serve') -PassThru -WindowStyle Hidden
    $caddy = Start-Process -FilePath 'caddy' -ArgumentList @('run', '--config', (Join-Path $here 'Caddyfile'), '--adapter', 'caddyfile') -PassThru -WindowStyle Hidden
    Remove-Item Env:\JARVIS_LOCAL_SPEECH_KEY
    for ($i = 0; $i -lt 30 -and -not (Test-Port $serverPort); $i++) { Start-Sleep -Seconds 1 }
    if (-not (Test-Port $serverPort)) {
        Write-Host 'The kit''s server did not start. Run the self-test (start-kit.ps1 -SelfTest) and copy what it prints into JARVIS''s chat.'
        exit 1
    }

    & tailscale funnel --bg --https=$HttpsPort $gatePort | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Host 'Tailscale Funnel did not start. Check that Funnel is allowed for your tailnet (Tailscale admin console > Access controls) and that you are signed in. See README.md.'
        exit 1
    }
    $funnelOn = $true

    $status = (& tailscale funnel status 2>$null) -join "`n"
    $pattern = if ($HttpsPort -eq 443) { 'https://[A-Za-z0-9.-]+\.ts\.net(?![:0-9])' } else { "https://[A-Za-z0-9.-]+\.ts\.net:$HttpsPort" }
    $m = [regex]::Match($status, $pattern)
    $address = if ($m.Success) { $m.Value } else { "run 'tailscale funnel status' to see it" }

    Write-Host ''
    Write-Host 'The laptop speech kit is running.'
    Write-Host "Address: $address"
    Write-Host "Key: $key"
    Write-Host ''
    Write-Host 'Give both to JARVIS once (README step 6): the address is JARVIS_LOCAL_SPEECH_URL, the key goes in the secret jarvis-local-speech-key.'
    Write-Host 'Keep this window open and the laptop awake. Ctrl+C stops it.'

    if ($SelfTest) {
        Write-Host ''
        $env:JARVIS_LOCAL_SPEECH_KEY = $key
        & $py -I -m jarvis.localspeech selftest
        Remove-Item Env:\JARVIS_LOCAL_SPEECH_KEY
    }

    Wait-Process -Id $caddy.Id
} finally {
    if (Test-Path Env:\JARVIS_LOCAL_SPEECH_KEY) { Remove-Item Env:\JARVIS_LOCAL_SPEECH_KEY }
    if ($caddy -and -not $caddy.HasExited) { Stop-Process -Id $caddy.Id -Force -ErrorAction SilentlyContinue }
    if ($server -and -not $server.HasExited) { Stop-Process -Id $server.Id -Force -ErrorAction SilentlyContinue }
    # close only this port, and only if THIS run opened it (never `funnel reset`)
    if ($funnelOn) { & tailscale funnel --https=$HttpsPort off 2>$null | Out-Null }
}
