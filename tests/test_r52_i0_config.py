# tests/test_r52_i0_config.py -- R5.2 I0: the laptop speech kit's config keys (its Tailscale https
# address and its gate key as `SecretStr`; row 392's rule: http refused) and the voice profile's
# switches, in `config_voice.LocalSpeechConfig`, a base class of `Settings`.
from __future__ import annotations

import pytest
from pydantic import SecretStr, ValidationError

from jarvis.config import Settings
from jarvis.config_voice import LocalSpeechConfig
from jarvis.localspeech import protocol as p

KEY = "k" * p.KEY_MIN_CHARS
URL = "https://my-laptop.tail1234.ts.net:8443"


def test_the_keys_and_their_defaults(settings: Settings) -> None:
    assert isinstance(settings, LocalSpeechConfig)
    assert settings.local_speech_url is None and settings.local_speech_key is None
    assert settings.local_speech_enabled is True and not settings.local_speech_configured
    assert settings.local_speech_timeout_s == 8.0 and settings.local_speech_health_s == 30
    assert settings.voice_profile_enabled is True
    assert settings.voice_session_compare_minutes == 20


def test_a_configured_kit_keeps_its_key_secret() -> None:
    s = Settings(_env_file=None, local_speech_url=URL, local_speech_key=SecretStr(KEY))
    assert s.local_speech_configured and s.local_speech_url == URL
    assert KEY not in repr(s) and KEY not in str(s)
    off = s.model_copy(update={"local_speech_enabled": False})
    assert not off.local_speech_configured


@pytest.mark.parametrize(
    "url",
    [
        "http://my-laptop.tail1234.ts.net",  # row 392: http refused
        "https://my-laptop.example.com",  # only the owner's Tailscale name
        "https://100.101.102.103",  # no IP address
        "https://my-laptop.tail1234.ts.net:9999",  # not a Funnel port
        "https://my-laptop.tail1234.ts.net/admin",  # no other path
        "https://user@my-laptop.tail1234.ts.net",
    ],
)
def test_an_address_outside_the_rule_is_refused(url: str) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, local_speech_url=url)


def test_the_address_is_normalised_and_a_short_key_refused() -> None:
    s = Settings(_env_file=None, local_speech_url="  HTTPS://My-Laptop.Tail1234.ts.net/v1/ ")
    assert s.local_speech_url == "https://my-laptop.tail1234.ts.net"
    assert Settings(_env_file=None, local_speech_url="").local_speech_url is None
    with pytest.raises(ValidationError):
        Settings(_env_file=None, local_speech_key=SecretStr("too-short"))
    with pytest.raises(ValidationError):
        Settings(_env_file=None, local_speech_timeout_s=0.1)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, voice_session_compare_minutes=31)
