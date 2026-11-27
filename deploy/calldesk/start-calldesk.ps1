# Starts the JARVIS call desk and its watchdog in the background (the Start-menu shortcut, sign-in
# and start-home.ps1 run this hidden). Safe to run any time: a second copy notices the first and
# stops at once. The desk first puts back any sound setting a crash or a restart left behind.
$ErrorActionPreference = 'Stop'
$Kit = Split-Path -Parent $MyInvocation.MyCommand.Path
$Data = Join-Path $env:LOCALAPPDATA 'JARVIS\CallDesk'
$PyW = Join-Path $Kit '.venv\Scripts\pythonw.exe'
if (-not (Test-Path -LiteralPath $PyW)) {
    Write-Host 'The call desk is not installed yet: run install-calldesk.ps1 first (README step 4).'
    exit 1
}
New-Item -ItemType Directory -Force -Path $Data | Out-Null
Remove-Item -LiteralPath (Join-Path $Data 'stop.request') -ErrorAction SilentlyContinue
Start-Process -FilePath $PyW -ArgumentList @('-I', '-m', 'jarvis.calldesk', 'supervise') -WorkingDirectory $Data -WindowStyle Hidden
Write-Host 'The JARVIS call desk is running. To stop it: Start -> JARVIS -> JARVIS Call Desk - Stop.'
