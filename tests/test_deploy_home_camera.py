# tests/test_deploy_home_camera.py -- R3 D7/D13/D16/D20: the Frigate template and the optional model
# export, checked by text and structure (nothing is run).
from __future__ import annotations

import re
from pathlib import Path

import yaml

HOME = Path(__file__).resolve().parents[1] / "deploy" / "home"
CFG = (HOME / "frigate" / "config.yml").read_text()
DOC = yaml.safe_load(CFG)


def test_the_template_is_valid_yaml_with_the_documented_shape() -> None:
    cam = DOC["cameras"]["gate"]
    assert DOC["mqtt"]["enabled"] is True and DOC["mqtt"]["host"] == "mosquitto"
    assert DOC["detectors"]["cpu1"]["type"] == "cpu"
    assert (cam["detect"]["width"], cam["detect"]["height"], cam["detect"]["fps"]) == (1280, 720, 5)
    assert cam["review"]["alerts"]["required_zones"] == ["gate"]
    assert set(cam["zones"]) == {"gate", "doorstep"}
    assert DOC["face_recognition"] == {"enabled": True, "model_size": "small", "save_attempts": 20}


def test_no_zone_covers_anything_until_the_owner_draws_it() -> None:
    """D20: nothing public. Each placeholder polygon fits inside a 6 % x 8 % corner."""
    for zone in DOC["cameras"]["gate"]["zones"].values():
        xs_ys = [float(v) for v in str(zone["coordinates"]).split(",")]
        xs, ys = xs_ys[0::2], xs_ys[1::2]
        assert max(xs) <= 0.06 and max(ys) <= 0.08


def test_retention_is_short_and_nothing_is_recorded_all_the_time() -> None:
    rec = DOC["record"]
    assert rec["continuous"]["days"] == 0 and rec["motion"]["days"] == 0
    assert rec["alerts"]["retain"]["days"] == 7 and rec["detections"]["retain"]["days"] == 3
    assert DOC["snapshots"]["retain"]["default"] == 7


def test_no_secret_or_address_is_written_in_the_template() -> None:
    assert "{FRIGATE_GATE_RTSP}" in CFG and "{FRIGATE_MQTT_PASSWORD}" in CFG
    for url in re.findall(r"rtsp://\S+", CFG):
        assert url.startswith("rtsp://127.0.0.1:8554/")  # the go2rtc restream, no login in it
    assert not re.search(r"password:\s*[^\"{\s]", CFG)
    assert not re.search(
        r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}:\d+/", CFG.replace("127.0.0.1:8554", "")
    )


def test_the_words_for_the_owner_say_to_keep_public_places_out() -> None:
    text = (HOME / "frigate" / "README.txt").read_text()
    assert "road" in text and "neighbour" in text and "must not watch" in text
    assert "Train the doorstep model" in text and "laptop is asleep or off" in text
    assert "not a monitored alarm" in text
    assert "Draw zones" in CFG or "redraw" in CFG


def test_the_export_script_is_optional_changes_nothing_by_itself_and_is_ascii() -> None:
    ps = (HOME / "export-yolov9.ps1").read_text()
    assert ps.isascii() and "OPTIONAL" in ps and "never edits" in ps
    assert "Remove-Item" not in ps and "Invoke-Expression" not in ps and "iex " not in ps
    assert "yolov9-t-320.onnx" in ps and "type: openvino" in ps
    assert (HOME / "frigate" / "README.txt").read_text().isascii() and CFG.isascii()
