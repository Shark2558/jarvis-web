# tests/test_r64_c_private_host.py — R6.4 D8 (workbook row 392): a Tailscale name (`*.ts.net`) is
# not a private host for the custom AI address's plain-http rule. Seen from Cloud Run such a name
# resolves through public DNS to Tailscale's relays (Funnel), so `http://` would carry the API key
# across the Internet in clear text: https is required. Plain http stays allowed for localhost,
# loopback, RFC 1918 / ULA / link-local addresses, `.local` / `.internal` / host.docker.internal
# and single-label names.
from __future__ import annotations

from pathlib import Path

import pytest

from jarvis.config import Settings, _is_private_host

ROOT = Path(__file__).resolve().parents[1]


def _url(url: str) -> str | None:
    s = Settings(_env_file=None, env="dev", openai_compat_base_url=url)  # type: ignore[call-arg]
    return s.openai_compat_base_url


@pytest.mark.parametrize(
    "host", ["box.tail1234.ts.net", "BOX.TAIL1234.TS.NET", "ts.net", "a.b.c.ts.net"]
)
def test_a_tailscale_name_is_not_a_private_host(host: str) -> None:
    assert _is_private_host(host) is False


@pytest.mark.parametrize(
    "url",
    [
        "http://box.tail1234.ts.net/v1",
        "http://box.tail1234.ts.net:443/v1",
        "http://box.tail1234.ts.net:8443/v1",
        "http://box.tail1234.ts.net./v1",  # a trailing dot is no way round it
    ],
)
def test_plain_http_to_a_tailscale_name_is_refused_and_names_https(url: str) -> None:
    with pytest.raises(ValueError, match="https://") as ei:
        _url(url)
    assert "Tailscale" in str(ei.value) or "non-local" in str(ei.value)


def test_the_tailscale_refusal_says_why_in_plain_words() -> None:
    with pytest.raises(ValueError) as ei:
        _url("http://box.tail1234.ts.net/v1")
    text = str(ei.value)
    assert "Tailscale" in text and "https://" in text and "clear text" in text


def test_https_on_a_tailscale_name_is_accepted() -> None:
    assert _url("https://box.tail1234.ts.net/v1/") == "https://box.tail1234.ts.net/v1"
    assert _url("https://box.tail1234.ts.net:8443/v1") == "https://box.tail1234.ts.net:8443/v1"


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:11434/v1",
        "http://127.0.0.1:11434/v1",
        "http://[::1]:11434/v1",
        "http://10.0.0.5:8000/v1",
        "http://172.16.4.2:8000/v1",
        "http://192.168.1.20:11434/v1",
        "http://[fd12:3456::1]:8000/v1",  # ULA
        "http://169.254.10.10:8000/v1",  # link-local
        "http://laptop.local:11434/v1",
        "http://ollama.internal:11434/v1",
        "http://host.docker.internal:11434/v1",
        "http://ollama:11434/v1",  # single-label name on a compose network
    ],
)
def test_the_allowed_private_cases_are_unchanged(url: str) -> None:
    assert _url(url) == url


@pytest.mark.parametrize("url", ["http://api.groq.com/openai/v1", "http://8.8.8.8/v1"])
def test_a_public_host_still_needs_https(url: str) -> None:
    with pytest.raises(ValueError, match="https://"):
        _url(url)


def _url_case() -> str:
    """The custom brain's URL check, cut out of deploy/cloudrun.sh as it is."""
    script = (ROOT / "deploy" / "cloudrun.sh").read_text(encoding="utf-8")
    start = script.index('  case "$C_URL" in')
    return script[start : script.index("  esac", start) + len("  esac")]


@pytest.mark.parametrize(
    ("url", "ok"),
    [
        ("https://box.tail1234.ts.net/v1", True),
        ("https://api.groq.com/openai/v1", True),
        ("http://localhost:11434/v1", True),
        ("http://127.0.0.1:11434/v1", True),
        ("http://box.tail1234.ts.net/v1", False),
        ("http://box.tail1234.ts.net:8443/v1", False),
        ("http://box.tail1234.ts.net", False),
        ("http://api.groq.com/openai/v1", False),
    ],
)
def test_the_cloud_run_deploy_script_refuses_http_to_a_tailscale_name(url: str, ok: bool) -> None:
    import shutil
    import subprocess

    bash = shutil.which("bash")
    assert bash is not None
    snippet = 'die() { echo "$1"; exit 3; }\nC_URL="$1"\n' + _url_case() + "\necho accepted\n"
    r = subprocess.run(  # noqa: S603 - a fixed script, the URL is an argument
        [bash, "-c", snippet, "check", url], capture_output=True, text=True, timeout=10
    )
    assert (r.returncode == 0 and "accepted" in r.stdout) is ok, r.stdout
    if url.startswith("http://box."):
        assert "Tailscale" in r.stdout and "https://" in r.stdout
