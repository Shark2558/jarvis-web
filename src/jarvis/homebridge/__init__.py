# src/jarvis/homebridge/__init__.py
"""The JARVIS home bridge (R3 D3-D8): the only thing on the laptop the internet can reach.

It runs at home (Docker, `deploy/home/`), never in the cloud app, and ships in the home kit with
`jarvis/home/{ports,signing}.py`. Its parts are plugins (`plugins.BridgePlugin`) listed in
`registry.PLUGINS`. Nothing is imported here, so `python -m jarvis.homebridge` stays light.
"""
