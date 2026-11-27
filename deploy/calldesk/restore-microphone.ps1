# Puts your own microphone and notification sounds back, now (the call desk does this by itself
# after every call, after a crash and when it starts; this is the button for "just in case").
param([switch]$NoPause)
$ErrorActionPreference = 'Stop'
$Kit = Split-Path -Parent $MyInvocation.MyCommand.Path
$Py = Join-Path $Kit '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $Py)) {
    Write-Host 'The call desk is not installed. To choose your microphone by hand: Settings -> System -> Sound -> Input.'
} else {
    & $Py -I -m jarvis.calldesk restore
    if ($LASTEXITCODE -ne 0) { Write-Host 'If it is still wrong: Settings -> System -> Sound -> Input, and choose your microphone.' }
}
if (-not $NoPause) { Read-Host 'Press Enter to close' | Out-Null }
