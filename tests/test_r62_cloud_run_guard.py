# tests/test_r62_cloud_run_guard.py -- R6.2 Part 1, gap G11 (Phase A findings 9.7 C8, decision 6):
# dev-only settings never start on Cloud Run. Cloud Run sets K_SERVICE on every service; with it,
# JARVIS_ENV=dev or JARVIS_AUTH_MODE=token is a start-up error (Settings.require_prod_invariants,
# which create_app and `jarvis chat` call). Without K_SERVICE (a laptop) dev and token mode start.
from __future__ import annotations

import pytest
from pydantic import SecretStr

from jarvis.api.app import create_app
from jarvis.config import AuthMode, LLMBackend, Settings


def _prod_google(settings: Settings, **extra: object) -> Settings:
    return settings.model_copy(
        update={
            "env": "prod",
            "api_token": SecretStr("t"),
            "auth_mode": AuthMode.GOOGLE,
            "google_client_id": "cid",
            "google_client_secret": SecretStr("s"),
            "session_secret": SecretStr("y" * 32),
            "public_base_url": "https://j.example",
            "owner_emails": ["a@b.c"],
            **extra,
        }
    )


def test_cloud_runs_own_variable_is_read(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("K_SERVICE", "jarvis")
    assert Settings(_env_file=None).cloud_run_service == "jarvis"
    monkeypatch.delenv("K_SERVICE")
    assert Settings(_env_file=None).cloud_run_service is None


def test_dev_on_cloud_run_refuses_to_start(settings: Settings) -> None:
    s = _prod_google(settings, env="dev", cloud_run_service="jarvis")
    with pytest.raises(RuntimeError, match="JARVIS_ENV=dev.*Cloud Run"):
        s.require_prod_invariants()


def test_token_mode_on_cloud_run_refuses_to_start(settings: Settings) -> None:
    s = _prod_google(settings, auth_mode=AuthMode.TOKEN, cloud_run_service="jarvis")
    with pytest.raises(RuntimeError, match="JARVIS_AUTH_MODE=token.*Cloud Run"):
        s.require_prod_invariants()


def test_production_on_cloud_run_starts(settings: Settings) -> None:
    _prod_google(settings, cloud_run_service="jarvis").require_prod_invariants()


def test_a_laptop_keeps_dev_and_token_mode(settings: Settings) -> None:
    assert settings.cloud_run_service is None and settings.auth_mode is AuthMode.TOKEN
    settings.require_prod_invariants()  # dev, token mode, no K_SERVICE: starts as before
    empty = settings.model_copy(update={"cloud_run_service": ""})  # Cloud Run never sets it empty
    empty.require_prod_invariants()


def test_the_refusal_comes_before_anything_is_built(settings: Settings) -> None:
    s = settings.model_copy(
        update={"cloud_run_service": "jarvis", "llm_backend": LLMBackend.MOCK}
    )  # dev + token mode, as a mistaken deploy would carry them
    with pytest.raises(RuntimeError, match="Cloud Run"):
        create_app(s)


def test_the_message_names_settings_only_never_a_value(settings: Settings) -> None:
    s = settings.model_copy(update={"cloud_run_service": "secret-looking-service-name"})
    with pytest.raises(RuntimeError) as got:
        s.require_prod_invariants()
    assert "secret-looking-service-name" not in str(got.value)
