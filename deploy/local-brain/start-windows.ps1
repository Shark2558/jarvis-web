# deploy/local-brain/start-windows.ps1 -- R1 offline mode, Windows (plan D10). Owner's laptop, no
# Python needed. Runs the access gate (Caddy) in front of Ollama and publishes it with Tailscale
# Funnel, then prints the address and key to paste into JARVIS: Integrations -> Offline mode.
#
# Needs: Ollama running (ollama.com), Caddy (caddyserver.com or: winget install CaddyServer.Caddy),
# Tailscale signed in with Funnel allowed (see README.md). Leave this window open; Ctrl+C or closing
# it stops the gate and closes Funnel. The key is made on the first run and kept in a file only you
# can read.
#
# Run it with:  powershell -ExecutionPolicy Bypass -File start-windows.ps1
$ErrorActionPreference = 'Stop'

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$dir = if ($env:JARVIS_LOCAL_BRAIN_DIR) { $env:JARVIS_LOCAL_BRAIN_DIR } else { Join-Path $env:LOCALAPPDATA 'JarvisLocalBrain' }
$keyFile = Join-Path $dir 'key'

function Need([string]$name, [string]$hint) {
    if (-not (Get-Command $name -ErrorAction SilentlyContinue)) {
        Write-Host "Missing: $name. $hint"
        exit 1
    }
}
Need 'caddy' 'Install it with: winget install CaddyServer.Caddy'
Need 'tailscale' 'Install it from https://tailscale.com/download and sign in.'

function Test-Ollama {
    try { Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/version' -TimeoutSec 3 | Out-Null; return $true } catch { return $false }
}

# Ollama's default context window is 4096 tokens; JARVIS's prompt and tool list need more, and an
# overflow silently drops the oldest words. A server started here gets 8192. One that is already
# running (the Ollama app) keeps its own setting: see README.md.
$ollama = $null
if (-not (Test-Ollama) -and (Get-Command 'ollama' -ErrorAction SilentlyContinue)) {
    $env:OLLAMA_CONTEXT_LENGTH = '8192'
    $ollama = Start-Process -FilePath 'ollama' -ArgumentList @('serve') -PassThru -WindowStyle Hidden
    Remove-Item Env:\OLLAMA_CONTEXT_LENGTH
    for ($i = 0; $i -lt 15 -and -not (Test-Ollama); $i++) { Start-Sleep -Seconds 1 }
}
if (-not (Test-Ollama)) {
    Write-Host 'Ollama is not answering on this laptop. Open the Ollama app (or run: $env:OLLAMA_CONTEXT_LENGTH=8192; ollama serve), then pull a model, for example: ollama pull qwen2.5:3b'
    exit 1
}

# Refuse to start twice: a second run would fight the first over the gate port, and its exit would
# close the first run's Funnel.
$probe = New-Object System.Net.Sockets.TcpClient
try {
    $probe.Connect('127.0.0.1', 11435)
    Write-Host 'Port 11435 is already in use, probably by a gate that is already running. Close that window (or stop whatever uses the port), then run this again.'
    exit 1
} catch [System.Net.Sockets.SocketException] {
    # nothing listens: good
} finally {
    $probe.Dispose()
}

if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir | Out-Null }
# only you (and no inherited group) can read the folder and the key: lock it BEFORE the key exists
& icacls $dir /inheritance:r /grant:r "$($env:USERNAME):(OI)(CI)F" | Out-Null
if (-not (Test-Path $keyFile) -or (Get-Item $keyFile).Length -eq 0) {
    # 32 random bytes, base64url, no padding (43 characters)
    $bytes = New-Object byte[] 32
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    $new = [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')
    [System.IO.File]::WriteAllText($keyFile, $new)
}
$key = (Get-Content -Raw $keyFile).Trim()
if ($key.Length -lt 16) {
    Write-Host "The key in $keyFile is too short (it needs 16+ characters). Delete that file and run this again to make a new key (then paste the new key into JARVIS)."
    exit 1
}

$caddy = $null
$funnelOn = $false
try {
    # The key goes to Caddy through its environment only (never on a command line).
    $env:JARVIS_LOCAL_KEY = $key
    $caddy = Start-Process -FilePath 'caddy' -ArgumentList @('run', '--config', (Join-Path $here 'Caddyfile'), '--adapter', 'caddyfile') -PassThru -WindowStyle Hidden
    Remove-Item Env:\JARVIS_LOCAL_KEY
    Start-Sleep -Seconds 1

    & tailscale funnel --bg --https=8443 11435 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Host 'Tailscale Funnel did not start. Check that Funnel is allowed for your tailnet (Tailscale admin console > Access controls) and that you are signed in. See README.md.'
        exit 1
    }
    $funnelOn = $true

    $status = (& tailscale funnel status 2>$null) -join "`n"
    $m = [regex]::Match($status, 'https://[A-Za-z0-9.-]+\.ts\.net(:[0-9]+)?')
    $address = if ($m.Success) { $m.Value } else { "run 'tailscale funnel status' to see it" }

    Write-Host ''
    Write-Host 'Offline mode gate is running.'
    Write-Host "Address: $address"
    Write-Host "Key: $key"
    Write-Host ''
    Write-Host 'Paste both into JARVIS > Integrations > Offline mode, press Test, then switch it On.'
    Write-Host 'Keep this window open and the laptop awake. Ctrl+C stops it.'

    Wait-Process -Id $caddy.Id
} finally {
    if ($caddy -and -not $caddy.HasExited) { Stop-Process -Id $caddy.Id -Force -ErrorAction SilentlyContinue }
    # close only this port, and only if THIS run opened it
    if ($funnelOn) { & tailscale funnel --https=8443 off 2>$null | Out-Null }
    if ($ollama -and -not $ollama.HasExited) { Stop-Process -Id $ollama.Id -Force -ErrorAction SilentlyContinue }
}
