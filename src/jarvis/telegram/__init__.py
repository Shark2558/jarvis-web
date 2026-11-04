# src/jarvis/telegram/__init__.py
"""Telegram front door and alerts (R1 D1-D6; Layer 1 surface, Layer 8 notifications).

Bot API over httpx (no SDK), webhook transport, one owner paired by a one-time code.
Importing this package imports nothing heavy; use the submodules.
"""
