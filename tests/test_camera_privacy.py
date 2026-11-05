# tests/test_camera_privacy.py -- R3 D14: the home feed row (count, export without names, passkey
# delete), the "at home" row, the camera data wipe, the bridge state part and the settings push.
from __future__ import annotations

import json

import pytest
from camera_fakes import PERSON, T0, UID, rig

from jarvis.camera.config import CameraConfigService
from jarvis.camera.models import CameraConfig, FeedItem
from jarvis.camera.ports import CameraUnavailable
from jarvis.camera.privacy import CameraData, CameraHomePrivacy, HomeFeedPrivacy
from jarvis.camera.state import CameraStateSource
from jarvis.privacy.ports import PrivacyRegistry, PrivacySource


async def test_home_feed_row_counts_exports_and_deletes_with_a_passkey() -> None:
    r = await rig()
    src = HomeFeedPrivacy(r.feed)
    assert isinstance(src, PrivacySource)
    empty = await src.describe(UID)
    assert empty.count == 0 and empty.delete == "none" and empty.retention == "7 days"
    await r.feed.add(
        UID, FeedItem(at=T0, kind="intruder", camera="gate", person=PERSON, score=0.95)
    )
    row = await src.describe(UID)
    assert row.count == 1 and row.delete == "passkey" and row.export and row.encrypted_by_jarvis
    assert row.rev and row.rev != empty.rev
    out = await src.export(UID)
    assert out is not None and out["entries"][0]["person"] == PERSON
    assert await src.delete(UID) == 1
    assert (await src.describe(UID)).count == 0


async def test_without_a_key_the_row_says_so() -> None:
    src = HomeFeedPrivacy(None)
    row = await src.describe(UID)
    assert row.count == 0 and "no encryption key" in row.note
    assert await src.export(UID) is None and await src.delete(UID) == 0


async def test_the_at_home_row_is_explained_and_not_deletable_here() -> None:
    row = await CameraHomePrivacy().describe(UID)
    assert row.delete == "none" and row.count is None and "laptop" in row.where
    reg = PrivacyRegistry()
    reg.register(CameraHomePrivacy())
    reg.register(HomeFeedPrivacy(None))
    assert reg.ids() == ["camera_home", "home_feed"]


async def test_wipe_removes_arm_state_and_settings() -> None:
    r = await rig()
    await r.alarm.arm(UID, "away", "console")
    data = CameraData(r.alarm, r.config)
    out = await data.export(UID)
    assert out["alarm"]["armed"] is True and out["cameras"]["gate"]["label"] == "Gate"
    await data.wipe(UID)
    assert (await r.alarm.view(UID)).armed is False
    assert (await r.config.get(UID)).cameras == {}


async def test_state_part_carries_the_arm_state_and_camera_settings() -> None:
    r = await rig()
    await r.alarm.arm(UID, "night", "console")
    part = await CameraStateSource(r.alarm, r.config).state_part(UID)
    assert (
        part.arm is not None and part.arm.armed and part.arm.mode == "night" and part.arm.rev == 1
    )
    assert part.settings is not None
    assert part.settings.cameras["gate"].alarm_zones == ("gate",)
    assert part.settings.snapshot is False and part.settings.packages is True
    assert part.faces is None and part.devices is None


async def test_snapshot_flag_follows_the_owners_opt_in() -> None:
    r = await rig()
    assert (await r.config.settings_state(UID)).snapshot is False
    r.snap.on = True
    assert (await r.config.settings_state(UID)).snapshot is True


async def test_saving_cameras_pushes_the_settings_and_a_dead_laptop_only_skips_the_push() -> None:
    r = await rig(camera=False)
    cams = {"gate": CameraConfig(label="  Front   gate ", alarm_zones=("gate", "gate"))}
    saved = await r.config.set_cameras(UID, cams, retention_days=14)
    assert saved.rev == 1 and saved.cameras["gate"].label == "Front gate"
    assert saved.cameras["gate"].alarm_zones == ("gate",)
    method, path, body, _ = r.caller.calls[-1]
    assert (method, path) == ("POST", "/bridge/v1/state")
    assert body is not None and body["settings"]["retention_days"] == 14
    r.caller.online = False
    again = await r.config.set_cameras(UID, cams)
    assert again.rev == 2 and again.retention_days == 14


async def test_settings_are_sealed_and_a_corrupt_record_is_never_overwritten() -> None:
    r = await rig()
    dump = json.dumps(r.docs._data, default=str)
    assert "Gate" not in dump and "doorstep" not in dump
    r.docs._data[f"jarvis_home_cameras/{UID}"]["blob"] = "x"
    before = dict(r.docs._data[f"jarvis_home_cameras/{UID}"])
    with pytest.raises(CameraUnavailable):
        await r.config.set_cameras(UID, {})
    assert r.docs._data[f"jarvis_home_cameras/{UID}"] == before


async def test_without_a_caller_nothing_is_pushed() -> None:
    r = await rig()
    cfg = CameraConfigService(r.docs, r.config._doc._ring)  # noqa: SLF001
    assert await cfg.push(UID) is False


async def test_a_wipe_never_takes_the_arm_rev_back_so_the_bridge_follows_the_next_arm() -> None:
    from pathlib import Path
    from tempfile import mkdtemp

    from jarvis.home.ports import BridgeState
    from jarvis.homebridge.arm import ArmState

    r = await rig()
    bridge = ArmState(Path(mkdtemp()) / "s.json")
    for _ in range(3):  # arm, disarm-less churn: modes flip the rev up
        await r.alarm.arm(UID, "away", "console")
        await r.alarm.arm(UID, "night", "console")
    before = (await r.alarm.record(UID)).rev
    bridge.apply(BridgeState(arm=(await CameraStateSource(r.alarm, r.config).state_part(UID)).arm))
    await CameraData(r.alarm, r.config).wipe(UID)
    after_wipe = await r.alarm.record(UID)
    assert after_wipe.rev > before and after_wipe.armed is False
    await r.alarm.arm(UID, "away", "console")
    part = await CameraStateSource(r.alarm, r.config).state_part(UID)
    bridge.apply(BridgeState(arm=part.arm))
    assert bridge.armed is True
