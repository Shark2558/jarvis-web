# Stops the JARVIS call desk and its watchdog, then puts your microphone and notification sounds
# back as you had them. JARVIS can't make calls from this laptop until you start it again.
param([switch]$NoPause)
$ErrorActionPreference = 'Stop'
$Kit = Split-Path -Parent $MyInvocation.MyCommand.Path
$Data = Join-Path $env:LOCALAPPDATA 'JARVIS\CallDesk'
$Py = Join-Path $Kit '.venv\Scripts\python.exe'

function Desk-Processes {
    Get-CimInstance Win32_Process -Filter "Name = 'pythonw.exe' OR Name = 'python.exe'" |
        Where-Object { $_.CommandLine -like '*jarvis.calldesk supervise*' -or $_.CommandLine -like '*jarvis.calldesk run*' }
}

New-Item -ItemType Directory -Force -Path $Data | Out-Null
Set-Content -LiteralPath (Join-Path $Data 'stop.request') -Value 'stop' -Encoding ASCII
Write-Host 'Stopping the JARVIS call desk (at most 15 seconds)...'
$deadline = (Get-Date).AddSeconds(15)
while ((Desk-Processes) -and ((Get-Date) -lt $deadline)) { Start-Sleep -Milliseconds 500 }
$left = @(Desk-Processes)
foreach ($p in $left) { Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue }
if (Test-Path -LiteralPath $Py) { & $Py -I -m jarvis.calldesk restore }
Write-Host 'The JARVIS call desk is stopped. To start it again: Start -> JARVIS -> JARVIS Call Desk.'
if (-not $NoPause) { Read-Host 'Press Enter to close' | Out-Null }
