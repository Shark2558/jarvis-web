# tests/test_r11_1_c_photos_off.py -- R11.1 O5 (plan D13): when the Photos Picker API is switched
# off in the owner's Google project, JARVIS names the service and the fix instead of the generic
# "that Google service is not switched on"; every other Google service keeps its own words.
from __future__ import annotations

import httpx
import pytest
from google_fakes import GOOGLE_UID, google_tokens
from pydantic import SecretStr

from jarvis.integrations.google import (
    PHOTOS_OFF_MSG,
    SERVICE_OFF_MSG,
    GoogleConnector,
    GoogleServiceDisabled,
)
from jarvis.integrations.vault import MemoryTokenStore
from jarvis.photos.models import PHOTOS_SCOPE
from jarvis.photos.picker import PickerClient

OFF = {"error": {"message": "vendor words 123456", "details": [{"reason": "SERVICE_DISABLED"}]}}


async def connector() -> GoogleConnector:
    store = MemoryTokenStore()
    await store.put(GOOGLE_UID, google_tokens(scopes=[PHOTOS_SCOPE]))
    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(403, json=OFF)))
    return GoogleConnector(store, client_id="c", client_secret=SecretStr("s"), http=http)


async def test_a_switched_off_picker_names_google_photos_and_the_fix() -> None:
    picker = PickerClient(await connector())
    with pytest.raises(GoogleServiceDisabled) as off:
        await picker.create_session(GOOGLE_UID)
    assert str(off.value) == PHOTOS_OFF_MSG
    assert PHOTOS_OFF_MSG == (
        "Google Photos Picker is not switched on for your JARVIS project yet: "
        "re-run deploy/cloudrun.sh."
    )
    assert "vendor" not in str(off.value) and "123456" not in str(off.value)


async def test_every_other_google_service_keeps_the_general_sentence() -> None:
    conn = await connector()
    for url in (
        "https://tasks.googleapis.com/tasks/v1/users/@me/lists",
        "https://photospicker.googleapis.com.evil.example/v1/sessions",
    ):
        with pytest.raises(GoogleServiceDisabled) as off:
            await conn.request(GOOGLE_UID, "GET", url)
        assert str(off.value) == SERVICE_OFF_MSG
