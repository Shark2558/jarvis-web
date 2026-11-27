# deploy/local-speech/install-kit.ps1 -- R5.2 "Your voice": the laptop speech kit's installer
# (Windows 10/11, plan D1). Open PowerShell (NOT as administrator: Start -> type PowerShell ->
# Windows PowerShell), go to this folder and type:
#   powershell -ExecutionPolicy Bypass -File .\install-kit.ps1
# After getting a newer copy of JARVIS's code (your key and recordings are kept):
#   powershell -ExecutionPolicy Bypass -File .\install-kit.ps1 -Update
# Safe to run again: every step checks first and skips what is already done. It installs Python
# 3.12 and Caddy only with your Y (both free, through Windows' own installer, for your user), makes
# the kit's private folder (only your account can open it), installs the kit's pinned,
# hash-checked packages there, downloads only the model files pinned in models.json (each checked
# against its SHA-256, its licence saved beside it), and adds a Start-menu shortcut.
# Nothing is spent and nothing is sent anywhere but the downloads.
param([switch]$Update)
$ErrorActionPreference = 'Stop'
$Kit = Split-Path -Parent $MyInvocation.MyCommand.Path
$Dir = if ($env:JARVIS_SPEECH_KIT_DIR) { $env:JARVIS_SPEECH_KIT_DIR } else { Join-Path $env:LOCALAPPDATA 'JARVIS\LocalSpeech' }
$Venv = Join-Path $Dir 'venv'
$Py = Join-Path $Venv 'Scripts\python.exe'
$Menu = Join-Path ([Environment]::GetFolderPath('Programs')) 'JARVIS'

function Say($text) { Write-Host ''; Write-Host "== $text" -ForegroundColor Cyan }
function Yes($text) { return ((Read-Host "$text Type Y and press Enter (anything else: no)") -match '^[Yy]$') }
function Stop-Here($text) { Write-Host $text -ForegroundColor Yellow; exit 1 }

# 0. Your own account, not administrator --------------------------------------------------------
$me = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if ($me.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Stop-Here 'Please use a normal PowerShell window, not "Run as administrator": the kit and its recordings belong to your own account. Close this window, open PowerShell from Start, and type the line again.'
}
if ($Kit.Contains("'") -or $Kit.Contains('"')) {
    Stop-Here 'The folder''s name has a quote mark in it. Move JARVIS''s folder to C:\JARVIS and run this again.'
}

function Find-Python {
    try {
        $found = & py -3.12 -c "import sys; print(sys.executable)" 2>$null
        if ($LASTEXITCODE -eq 0 -and $found) { return ($found | Select-Object -First 1).Trim() }
    } catch { }
    $local = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'
    if (Test-Path -LiteralPath $local) { return $local }
    return $null
}

function Find-Source {
    # the kit's code: kit-src\ beside this script (a kit zip), else this checkout's src\ folder
    $zip = Join-Path $Kit 'kit-src'
    if (Test-Path -LiteralPath (Join-Path $zip 'jarvis\localspeech')) { return $zip }
    $checkout = Join-Path (Split-Path -Parent (Split-Path -Parent $Kit)) 'src'
    if (Test-Path -LiteralPath (Join-Path $checkout 'jarvis\localspeech')) { return $checkout }
    return $null
}

# 1. Python 3.12 (free, from python.org, for your user only) ------------------------------------
Say 'Python 3.12'
$base = Find-Python
if (-not $base) {
    Write-Host 'Python 3.12 is not installed. It is free and comes from python.org; Windows'' own installer (winget) installs it for your user only.'
    if (-not (Yes 'Install it now?')) { Stop-Here 'Stopped. Nothing changed.' }
    winget install --exact --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) { Stop-Here 'The Python install did not finish. Copy the lines above into JARVIS''s chat.' }
    $base = Find-Python
    if (-not $base) { Stop-Here 'Python is installed. Close this window, open PowerShell again in this folder and type the same line again.' }
}
Write-Host 'Found Python 3.12.'

# 2. Caddy (the little gate that checks the key) and Tailscale ----------------------------------
Say 'Caddy and Tailscale'
if (-not (Get-Command 'caddy' -ErrorAction SilentlyContinue)) {
    Write-Host 'Caddy is not installed. It is free (caddyserver.com, Apache-2.0); winget installs it.'
    if (-not (Yes 'Install it now?')) { Stop-Here 'Stopped. Install Caddy (winget install CaddyServer.Caddy), then run this again.' }
    winget install --exact --id CaddyServer.Caddy --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) { Stop-Here 'The Caddy install did not finish. Copy the lines above into JARVIS''s chat.' }
    Write-Host 'Caddy is installed. If start-kit.ps1 later says "Missing: caddy", open a new PowerShell window.'
} else { Write-Host 'Found Caddy.' }
if (-not (Get-Command 'tailscale' -ErrorAction SilentlyContinue)) {
    Write-Host 'Tailscale is not installed yet: get it from https://tailscale.com/download, sign in, then allow Funnel (README step 3). The kit installs without it; start-kit.ps1 needs it.' -ForegroundColor Yellow
} else { Write-Host 'Found Tailscale.' }

# 3. The kit's private folder (your account only) -----------------------------------------------
Say 'The kit''s private folder'
New-Item -ItemType Directory -Force -Path $Dir | Out-Null
# only you (and no inherited group) can open the folder: the key and the recordings live here
& icacls $Dir /inheritance:r /grant:r "$($env:USERNAME):(OI)(CI)F" | Out-Null
if ($LASTEXITCODE -ne 0) { Stop-Here 'Could not make the kit''s folder private. Copy the lines above into JARVIS''s chat.' }
Write-Host 'Done (only your account can open it).'

# 4. The kit's packages (pinned and hash-checked, wheels only) ----------------------------------
Say 'The kit''s packages (pinned and hash-checked)'
if (-not (Test-Path -LiteralPath $Py)) {
    & $base -m venv $Venv
    if ($LASTEXITCODE -ne 0) { Stop-Here 'Could not make the kit''s Python environment. Copy the lines above into JARVIS''s chat.' }
    $Update = $true
}
if ($Update) {
    & $Py -m pip install --quiet --disable-pip-version-check --require-hashes --only-binary=:all: -r (Join-Path $Kit 'requirements-kit.txt')
    if ($LASTEXITCODE -ne 0) { Stop-Here 'Installing the packages failed. Copy the lines above into JARVIS''s chat.' }
}
Write-Host 'Done.'

# 5. The kit's own code -------------------------------------------------------------------------
Say 'The kit''s code'
$src = Find-Source
if (-not $src) { Stop-Here 'The kit''s code was not found next to this script. Use the whole JARVIS folder (README step 1).' }
$site = (& $Py -I -c "import sysconfig; print(sysconfig.get_paths()['purelib'])").Trim()
Set-Content -LiteralPath (Join-Path $site 'jarvis-local-speech.pth') -Value $src -Encoding Default
Write-Host 'Done.'

# 6. The model files (only those pinned in models.json; each SHA-256 checked) --------------------
Say 'Speech models'
$env:JARVIS_SPEECH_KIT_DIR = $Dir
$env:JARVIS_SPEECH_KIT_MANIFEST = Join-Path $Kit 'models.json'
& $Py -I -m jarvis.localspeech models
& $Py -I -m jarvis.localspeech models install
if ($LASTEXITCODE -ne 0) { Stop-Here 'A model did not install (nothing half-downloaded is kept). Copy the lines above into JARVIS''s chat.' }

# 7. Start-menu shortcut ------------------------------------------------------------------------
Say 'Shortcut'
New-Item -ItemType Directory -Force -Path $Menu | Out-Null
$shell = New-Object -ComObject WScript.Shell
$lnk = $shell.CreateShortcut((Join-Path $Menu 'JARVIS Speech Kit.lnk'))
$lnk.TargetPath = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$lnk.Arguments = "-NoProfile -ExecutionPolicy Bypass -NoExit -File `"$(Join-Path $Kit 'start-kit.ps1')`""
$lnk.WorkingDirectory = $Kit
$lnk.Description = 'JARVIS Speech Kit'
$lnk.Save()
Write-Host 'Start -> JARVIS -> JARVIS Speech Kit starts it.'

Say 'Finished'
& $Py -I -m jarvis.localspeech installed
Write-Host ''
Write-Host 'Now start the kit and run its self-test:'
Write-Host '  powershell -ExecutionPolicy Bypass -File .\start-kit.ps1 -SelfTest'
