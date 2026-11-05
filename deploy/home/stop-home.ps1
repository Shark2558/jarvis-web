# Stops JARVIS Home (camera and alarm alerts stop until you start it again).
$Distro = 'Ubuntu-24.04'
wsl -d $Distro -- bash -lc 'cd ~/jarvis-home && docker compose --env-file bridge.env --env-file images.env down'
Write-Host 'JARVIS Home is stopped. Run start-home.ps1 to start it again.'
