# JARVIS call desk (R18 "Calls from your laptop"): the installer. Open PowerShell (NOT as
# administrator: Start -> type PowerShell -> Windows PowerShell), then type:
#   cd C:\JARVIS-CallDesk
#   powershell -ExecutionPolicy Bypass -File .\install-calldesk.ps1
# Later, when JARVIS says the call desk is not linked (make a new code in JARVIS first):
#   powershell -ExecutionPolicy Bypass -File .\install-calldesk.ps1 -Link
# Later, after extracting a newer kit over this folder (your link and settings are kept):
#   powershell -ExecutionPolicy Bypass -File .\install-calldesk.ps1 -Update
# Later, after installing (or re-keying) the laptop speech kit on this laptop (R5.2):
#   powershell -ExecutionPolicy Bypass -File .\install-calldesk.ps1 -SpeechKit
# Safe to run again: every step checks first and skips what is already done. It installs Python
# 3.12 only with your Y, makes a private Python environment in this folder with the desk's
# pinned, hash-checked packages (no downloads of voice models), and adds Start-menu shortcuts.
param([switch]$Link, [switch]$Update, [switch]$SpeechKit)
$ErrorActionPreference = 'Stop'
$Kit = Split-Path -Parent $MyInvocation.MyCommand.Path
$Data = Join-Path $env:LOCALAPPDATA 'JARVIS\CallDesk'
$Venv = Join-Path $Kit '.venv'
$Py = Join-Path $Venv 'Scripts\python.exe'
$Menu = Join-Path ([Environment]::GetFolderPath('Programs')) 'JARVIS'
$Startup = [Environment]::GetFolderPath('Startup')

function Say($text) { Write-Host ''; Write-Host "== $text" -ForegroundColor Cyan }
function Yes($text) { return ((Read-Host "$text Type Y and press Enter (anything else: no)") -match '^[Yy]$') }
function Stop-Here($text) { Write-Host $text -ForegroundColor Yellow; exit 1 }

# 0. Your own account, not administrator ----------------------------------------------------------
$me = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if ($me.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Stop-Here 'Please use a normal PowerShell window, not "Run as administrator": the call desk works with your own sound settings. Close this window, open PowerShell from Start, and type the two lines again.'
}
if ($Kit.Contains("'") -or $Kit.Contains('"')) {
    Stop-Here 'The kit folder''s name has a quote mark in it. Extract the kit to C:\ (C:\JARVIS-CallDesk) and run this again.'
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

function Link-Desk {
    Say 'Link the call desk to JARVIS'
    Write-Host 'In JARVIS (console or phone): Calls -> Call desk -> "Link the call desk". It shows a code for a few minutes.'
    $code = Read-Host 'Type that code here and press Enter (Enter alone: later)'
    if (-not $code) { Write-Host 'Not linked yet. Later:  powershell -ExecutionPolicy Bypass -File .\install-calldesk.ps1 -Link'; return }
    & $Py -I -m jarvis.calldesk link $code
    if ($LASTEXITCODE -ne 0) { Write-Host 'Not linked. Make a new code in JARVIS, then:  powershell -ExecutionPolicy Bypass -File .\install-calldesk.ps1 -Link' }
}

# R5.2: the laptop speech kit's key, copied from the kit's own private folder into the desk's (your
# profile folder, like the desk's link); the desk then offers the kit's free speech for calls. The
# key is never printed and never put in this kit folder.
function Copy-SpeechKey {
    $kitDir = if ($env:JARVIS_SPEECH_KIT_DIR) { $env:JARVIS_SPEECH_KIT_DIR } else { Join-Path $env:LOCALAPPDATA 'JARVIS\LocalSpeech' }
    $from = Join-Path $kitDir 'key'
    if (-not (Test-Path -LiteralPath $from)) { Write-Host 'No laptop speech kit on this laptop: calls use cloud speech.'; return }
    New-Item -ItemType Directory -Force -Path $Data | Out-Null
    Copy-Item -LiteralPath $from -Destination (Join-Path $Data 'local-speech.key') -Force
    Write-Host 'The laptop speech kit is on this laptop: the call desk can use its free speech (restart the desk).'
}

function New-Shortcut($folder, $name, $script, [switch]$Hidden) {
    New-Item -ItemType Directory -Force -Path $folder | Out-Null
    $shell = New-Object -ComObject WScript.Shell
    $lnk = $shell.CreateShortcut((Join-Path $folder "$name.lnk"))
    $lnk.TargetPath = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $style = ''
    if ($Hidden) { $style = '-WindowStyle Hidden ' }
    $lnk.Arguments = "-NoProfile -ExecutionPolicy Bypass $style-File `"$(Join-Path $Kit $script)`""
    $lnk.WorkingDirectory = $Kit
    $lnk.Description = $name
    $lnk.Save()
}

if ($Link) {
    if (-not (Test-Path -LiteralPath $Py)) { Stop-Here 'The call desk is not installed yet: run install-calldesk.ps1 without -Link first.' }
    Link-Desk
    exit 0
}

# 1. Python 3.12 (free, from python.org, for your user only) --------------------------------------
Say 'Python 3.12'
$base = Find-Python
if (-not $base) {
    Write-Host 'Python 3.12 is not installed. It is free and comes from python.org; Windows'' own installer (winget) installs it for your user only.'
    if (-not (Yes 'Install it now?')) { Stop-Here 'Stopped. Nothing changed.' }
    winget install --exact --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) { Stop-Here 'The Python install did not finish. Copy the lines above to Claude.' }
    $base = Find-Python
    if (-not $base) { Stop-Here 'Python is installed. Close this window, open PowerShell again in this folder and type the same line again.' }
}
Write-Host "Using $base"

# 2. VB-CABLE (README step 2) ---------------------------------------------------------------------
Say 'VB-CABLE'
$cable = Get-PnpDevice -Class AudioEndpoint -ErrorAction SilentlyContinue | Where-Object { $_.FriendlyName -like '*CABLE Output*' }
if (-not $cable) {
    Write-Host 'VB-CABLE is not installed yet. Do step 2 of README.txt (it needs one restart), then run this again.' -ForegroundColor Yellow
    if (-not (Yes 'Carry on without it for now?')) { Stop-Here 'Stopped. Nothing changed.' }
} else { Write-Host 'Found CABLE Output.' }

# 3. The call desk's private Python environment ---------------------------------------------------
Say 'The call desk''s packages (pinned and hash-checked)'
if (-not (Test-Path -LiteralPath $Py)) {
    & $base -m venv $Venv
    if ($LASTEXITCODE -ne 0) { Stop-Here 'Could not make the environment. Copy the lines above to Claude.' }
    $Update = $true
}
if ($SpeechKit) {
    Copy-SpeechKey
    exit 0
}
if ($Update) {
    & $Py -m pip install --quiet --disable-pip-version-check --require-hashes --only-binary=:all: -r (Join-Path $Kit 'requirements-calldesk.txt')
    if ($LASTEXITCODE -ne 0) { Stop-Here 'Installing the packages failed. Copy the lines above to Claude.' }
}
$site = (& $Py -c "import sysconfig; print(sysconfig.get_paths()['purelib'])").Trim()
Set-Content -LiteralPath (Join-Path $site 'jarvis-calldesk.pth') -Value (Join-Path $Kit 'desk-src') -Encoding Default
Write-Host 'Done.'

# 4. Where the desk keeps its link and settings (your own profile folder) -------------------------
New-Item -ItemType Directory -Force -Path $Data | Out-Null
Set-Content -LiteralPath (Join-Path $Data 'kit-folder.txt') -Value $Kit -Encoding UTF8

# 5. The link to JARVIS ---------------------------------------------------------------------------
if (-not (Test-Path -LiteralPath (Join-Path $Data 'secret.json'))) { Link-Desk }
else { Say 'Link'; Write-Host 'Already linked (to link again: -Link).' }

# 5b. The laptop speech kit, when it is on this laptop (R5.2) -------------------------------------
Say 'Laptop speech kit'
Copy-SpeechKey

# 6. Start-menu shortcuts and start at sign-in ----------------------------------------------------
Say 'Shortcuts'
New-Shortcut $Menu 'JARVIS Call Desk' 'start-calldesk.ps1' -Hidden
New-Shortcut $Menu 'JARVIS Call Desk - Stop' 'stop-calldesk.ps1'
New-Shortcut $Menu 'JARVIS Call Desk - Give me back my microphone' 'restore-microphone.ps1'
Write-Host 'Start -> JARVIS has: JARVIS Call Desk, ... - Stop, ... - Give me back my microphone.'
$atSignIn = Join-Path $Startup 'JARVIS Call Desk.lnk'
if (-not (Test-Path -LiteralPath $atSignIn)) {
    Write-Host 'Starting the call desk when you sign in also puts your microphone back after a crash or a restart.'
    if (Yes 'Start it when you sign in? (recommended)') { New-Shortcut $Startup 'JARVIS Call Desk' 'start-calldesk.ps1' -Hidden }
}

# 7. Start it and check the laptop ----------------------------------------------------------------
Say 'Starting the call desk and checking this laptop'
& (Join-Path $Kit 'start-calldesk.ps1')
& $Py -I -m jarvis.calldesk check
Write-Host ''
Write-Host 'Finished. If the check listed something to fix, fix it and run the check again:'
Write-Host '  .\.venv\Scripts\python.exe -I -m jarvis.calldesk check'
