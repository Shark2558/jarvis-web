# Starts JARVIS Home (the "JARVIS Home" logon task runs this hidden). Safe to run any time.
$Distro = 'Ubuntu-24.04'
wsl -d $Distro -- bash -lc 'cd ~/jarvis-home && docker compose --env-file bridge.env --env-file images.env up -d'
