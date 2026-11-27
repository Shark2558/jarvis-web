# Starts JARVIS Home (the "JARVIS Home" logon task runs this hidden). Safe to run any time.
$Distro = 'Ubuntu-24.04'
wsl -d $Distro -- bash -lc 'cd ~/jarvis-home && docker compose --env-file bridge.env --env-file images.env up -d'
# R18: the JARVIS call desk too, when it is installed on this laptop (its installer notes its folder)
$deskKit = Join-Path $env:LOCALAPPDATA 'JARVIS\CallDesk\kit-folder.txt'
if (Test-Path -LiteralPath $deskKit) {
    $deskStart = Join-Path ((Get-Content -LiteralPath $deskKit -TotalCount 1).Trim()) 'start-calldesk.ps1'
    if (Test-Path -LiteralPath $deskStart) { & powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File $deskStart | Out-Null }
}
