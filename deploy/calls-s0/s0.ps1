# R18 S0 laptop test (docs/plans/r18-calls.md, section 10).
# Run from this folder:  powershell -ExecutionPolicy Bypass -File .\s0.ps1
# It finds Python 3.12 (and offers to install it, free, with Windows' own installer), makes a
# private Python environment inside this folder, installs the test's four pinned, hash-checked
# packages, makes the spoken test sentence with Windows' own voice, and runs the test.
# Nothing is sent anywhere and nothing is spent. Not run as administrator.

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot
Write-Host "JARVIS calls - laptop test (S0)"

# Python 3.12: through the "py" launcher, or where its installer puts it for one user.
$usePy = $false
$exe = $null
try {
    & py -3.12 -c "import sys" 2>$null
    if ($LASTEXITCODE -eq 0) { $usePy = $true }
} catch { }
if (-not $usePy) {
    $local = Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"
    if (Test-Path $local) { $exe = $local }
}

if (-not $usePy -and -not $exe) {
    Write-Host ""
    Write-Host "Python 3.12 is not installed. It is free and comes from python.org; Windows' own"
    Write-Host "installer (winget) installs it for your user only."
    $answer = Read-Host "Install it now? Type Y and press Enter (anything else stops)"
    if ($answer -ne "Y" -and $answer -ne "y") { Write-Host "Stopped. Nothing changed."; exit 1 }
    winget install --exact --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) { Write-Host "The Python install did not finish. Copy the message above to Claude."; exit 1 }
    Write-Host ""
    Write-Host "Python is installed. Close this window, open PowerShell again in this folder and"
    Write-Host "type the same line again."
    exit 0
}

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "Making the test's private Python environment (once)..."
    if ($usePy) { & py -3.12 -m venv .venv } else { & $exe -m venv .venv }
    if ($LASTEXITCODE -ne 0) { Write-Host "Could not make the environment. Copy the message above to Claude."; exit 1 }
}

Write-Host "Installing the test's packages (pinned and hash-checked)..."
& .\.venv\Scripts\python.exe -m pip install --quiet --disable-pip-version-check --require-hashes --only-binary=:all: -r requirements-s0.txt
if ($LASTEXITCODE -ne 0) { Write-Host "Installing the packages failed. Copy the message above to Claude."; exit 1 }

if (-not (Test-Path "phrase.wav")) {
    Add-Type -AssemblyName System.Speech
    $voice = New-Object System.Speech.Synthesis.SpeechSynthesizer
    $voice.Rate = -1
    $voice.SetOutputToWaveFile((Join-Path $PSScriptRoot "phrase.wav"))
    $voice.Speak("Hello. This is a JARVIS test call. If you can hear this sentence clearly, please say so. One, two, three, four, five.")
    $voice.Dispose()
}

& .\.venv\Scripts\python.exe .\s0_check.py
exit $LASTEXITCODE
