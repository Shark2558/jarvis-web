# tests/test_r52_v1_deploy.py -- R5.2 V1 (plan D1, 3.1, risk 2): deploy/local-speech/. The gate
# passes exactly the kit's API with the key (32+ characters, fail closed) on loopback in front of
# the server; Funnel on 10000 (the offline brain keeps 8443; 443 when 10000 is taken), never
# the server's port; the installer installs only hash-pinned wheels with licences written beside
# them and no GPL package; the manifest pins or leaves out every slot; the README in plain words.
# start-kit.sh is RUN here against stub caddy / tailscale / python programs.
from __future__ import annotations

import base64
import json
import re
import socket
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from jarvis import config_voice
from jarvis.localspeech import protocol as p
from jarvis.localspeech.kitconfig import ENV_KEY
from jarvis.localspeech.manager import load_manifest
from jarvis.offline.config import ALLOWED_PORTS

ROOT = Path(__file__).resolve().parents[1]
KIT = ROOT / "deploy" / "local-speech"
CADDY = (KIT / "Caddyfile").read_text()
INSTALL = (KIT / "install-kit.ps1").read_text()
START = (KIT / "start-kit.ps1").read_text()
UNIX = KIT / "start-kit.sh"
README = (KIT / "README.md").read_text()
REQS = (KIT / "requirements-kit.txt").read_text()


def _code(text: str) -> str:
    return "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))


def test_the_kit_has_exactly_the_planned_files() -> None:
    assert sorted(f.name for f in KIT.iterdir()) == [
        "Caddyfile",
        "README.md",
        "install-kit.ps1",
        "models.json",
        "requirements-kit.txt",
        "start-kit.ps1",
        "start-kit.sh",
    ]


# ---- the gate ------------------------------------------------------------------------------------
def _matchers(code: str) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for m in re.finditer(r"^\t@(\w+) \{\n(.*?)^\t\}", code, re.M | re.S):
        found[m.group(1)] = [ln.strip() for ln in m.group(2).splitlines() if ln.strip()]
    return found


def test_the_gate_listens_on_loopback_only_in_front_of_the_server() -> None:
    code = _code(CADDY)
    assert "bind 127.0.0.1" in code and "admin off" in code and "auto_https off" in code
    assert f":{p.GATE_PORT} {{" in code and "0.0.0.0" not in code and "[::]" not in code
    assert not re.search(rf"\S+:{p.GATE_PORT} \{{", code)  # no host before the port
    proxies = re.findall(r"reverse_proxy (\S+)", code)
    assert proxies == [f"127.0.0.1:{p.SERVER_PORT}"] * 3


def test_the_gate_passes_exactly_the_protocols_routes_and_only_with_the_key() -> None:
    m = _matchers(_code(CADDY))
    header = f'header Authorization "Bearer {{env.{ENV_KEY}}}"'
    passed: set[tuple[str, str]] = set()
    for name in ("get", "job", "post"):
        lines = m[name]
        assert header in lines, name
        method = next(ln.split()[1] for ln in lines if ln.startswith("method "))
        for ln in lines:
            if ln.startswith("path "):
                passed |= {(method, path.removeprefix("/v1")) for path in ln.split()[1:]}
            if ln.startswith("path_regexp "):
                regexp = ln.split(maxsplit=1)[1]
                assert re.fullmatch(regexp, "/v1" + p.job_path("job_0123456789ab"))
                assert not re.fullmatch(regexp, "/v1/jobs/job_0123456789ab/x")
                passed.add((method, p.JOBS))
    assert passed == set(p.ROUTES)
    gated = {path.removeprefix("/v1") for path in m["gated"][0].split()[1:]}
    assert gated == {path if path != p.JOBS else "/jobs/*" for _, path in p.ROUTES}


def test_the_gate_fails_closed_and_caps_bodies_as_the_protocol_does() -> None:
    code = _code(CADDY)
    assert f"@nokey expression `size({{env.{ENV_KEY}}}) < {p.KEY_MIN_CHARS}`" in code
    assert code.index("handle @nokey") < code.index("handle @get")
    size = re.search(r"max_size (\d+)MB", code)
    assert size and int(size.group(1)) * 1_000_000 == p.BODY_MAX
    assert "header_up -Authorization" not in code  # the server checks the key again


def test_every_refusal_of_the_gate_is_the_kits_json() -> None:
    bodies = re.findall(r"respond `(\{.*?\})` (\d{3})", CADDY)
    assert {int(s) for _, s in bodies} == {401, 404, 413, 502, 503}
    for body, _status in bodies:
        p.KitErrorBody.model_validate_json(body)
    assert CADDY.count("header Content-Type application/json") == len(bodies)


# ---- the packages --------------------------------------------------------------------------------
def _pins(text: str) -> dict[str, str]:
    return dict(re.findall(r"^([a-z0-9][a-z0-9._-]*)==(\S+) \\$", text, re.M))


def test_every_package_is_pinned_hashed_and_its_licence_written_beside_it() -> None:
    pins = _pins(REQS)
    assert len(pins) >= 30
    blocks = re.findall(
        r"^# ([a-z0-9._-]+) \(([^)]+)\): .+\n\1==\S+ \\\n"
        r"((?:    --hash=sha256:[0-9a-f]{64}(?: \\)?\n)+)",
        REQS,
        re.M,
    )
    assert {b[0] for b in blocks} == set(pins)
    for _name, licence, _hashes in blocks:
        assert "GPL" not in licence.replace("LGPL", "")
    code = [ln for ln in REQS.splitlines() if ln and not ln.startswith("#")]
    assert all(ln.startswith("    --hash=sha256:") or "==" in ln for ln in code)


def test_the_kit_installs_no_model_runtime_it_left_out() -> None:
    pins = _pins(REQS)
    for wanted in ("faster-whisper", "ctranslate2", "onnxruntime", "av", "starlette", "uvicorn"):
        assert wanted in pins
    for left_out in (
        "kokoro-onnx",
        "piper-tts",
        "phonemizer",
        "espeakng-loader",
        "torch",
        "openwakeword",
    ):
        assert left_out not in pins


def test_shared_packages_match_the_cloud_lock() -> None:
    lock = dict(
        re.findall(
            r"^([a-z0-9][a-z0-9._-]*)==(\S+) \\$", (ROOT / "requirements.lock").read_text(), re.M
        )
    )
    for name in ("pydantic", "pydantic-core", "starlette", "uvicorn", "cryptography", "h11"):
        assert _pins(REQS)[name] == lock[name], name


# ---- the manifest --------------------------------------------------------------------------------
def test_the_manifest_pins_or_leaves_out_every_slot_with_a_reason() -> None:
    manifest = load_manifest(KIT / "models.json")
    covered = {m.slot for m in manifest.models} | {m.slot for m in manifest.left_out}
    assert covered == set(p.EngineSlot)
    assert all(len(m.why) > 20 for m in manifest.left_out)
    assert all(m.licence is None or m.licence in p.PERMISSIVE_LICENCES for m in manifest.left_out)
    raw = json.loads((KIT / "models.json").read_text())
    assert raw["kit_version"] == "1.0.0"


WHISPER = (p.EngineSlot.WHISPER_SMALL, p.EngineSlot.WHISPER_MEDIUM)
WORKSHOP_OUT = {  # left out by the Workshop's decision, whatever their hashes
    p.EngineSlot.KOKORO: "GPL-3.0",
    p.EngineSlot.PIPER: "GPL-3.0",
    p.EngineSlot.INDIC_CONFORMER: "PyTorch",
    p.EngineSlot.INDIC_PARLER: "PyTorch",
}
UNHASHED = ("config.json", "tokenizer.json", "vocabulary.txt")  # plain git files on the Hub
# model.bin of each Whisper slot, checked on two Hugging Face pages (API tree's lfs.oid and the
# raw LFS pointer) at the revision; the README keeps them for whoever pins the slot.
WHISPER_MODEL_BIN = {
    "whisper-small": (
        "536b0662742c02347bc0e980a01041f333bce120",
        "3e305921506d8872816023e4c273e75d2419fb89b24da97b4fe7bce14170d671",
        "483,546,902",
    ),
    "whisper-medium": (
        "08e178d48790749d25932bbc082711ddcfdfbc4f",
        "9b45e1009dcc4ab601eff815b61d80e60ce3fd8c74c1a14f4a282258286b51ae",
        "1,527,906,378",
    ),
}
MODEL_ROW = r"^\| `([a-z-]+)` \| [^|]+ \| ([^|]+) \| (Pinned|Left out) \|"
HASH_ROW = (
    r"^\| `(whisper-[a-z]+)` \| `([0-9a-f]{40})` \| `model\.bin` \| `([0-9a-f]{64})` \|"
    r" ([0-9,]+) \|"
)


# I1 (the Workshop's decision): the three text files are pinned by their git blob id, read twice
# from the API tree at the revision (`oid`); README keeps them
WHISPER_BLOBS = {
    "whisper-small": {
        "config.json": ("e5047537059bd8f182d9ca64c470201585015187", 2370),
        "tokenizer.json": ("7818adb6de9fa3064d3ff81226fdd675be1f6344", 2203239),
        "vocabulary.txt": ("c9074644d9d1205686f16d411564729461324b75", 459861),
    },
    "whisper-medium": {
        "config.json": ("242aa06a480a7b5509375c645097e87af5136774", 2257),
        "tokenizer.json": ("7818adb6de9fa3064d3ff81226fdd675be1f6344", 2203239),
        "vocabulary.txt": ("c9074644d9d1205686f16d411564729461324b75", 459861),
    },
}
BLOB_ROW = r"^\| `(whisper-[a-z]+)` \| `([a-z.]+)` \| `([0-9a-f]{40})` \| ([0-9,]+) \|"


def test_english_hearing_is_pinned_at_its_commit_weights_by_sha256_text_by_blob_id() -> None:
    manifest = load_manifest(KIT / "models.json")
    for slot in WHISPER:
        entry = manifest.entry(slot)
        assert entry is not None and entry.licence == "MIT", slot
        assert entry.source == f"https://huggingface.co/Systran/faster-{slot.value}"
        revision, sha256, size = WHISPER_MODEL_BIN[slot.value]
        assert entry.revision == revision
        files = {f.name: f for f in entry.files}
        assert set(files) == {"model.bin", *UNHASHED}
        weights = files["model.bin"]
        assert (weights.sha256, f"{weights.size:,}", weights.git_blob_sha1) == (sha256, size, None)
        for name, (blob, length) in WHISPER_BLOBS[slot.value].items():
            assert (files[name].git_blob_sha1, files[name].size, files[name].sha256) == (
                blob,
                length,
                None,
            )
        base = f"https://huggingface.co/Systran/faster-{slot.value}/resolve/{revision}/"
        assert all(f.url == base + f.name for f in entry.files)


def test_the_readme_keeps_the_whisper_text_files_blob_ids() -> None:
    found: dict[str, dict[str, tuple[str, int]]] = {}
    for slot, name, blob, size in re.findall(BLOB_ROW, README, re.M):
        found.setdefault(slot, {})[name] = (blob, int(size.replace(",", "")))
    assert found == WHISPER_BLOBS


def test_the_workshops_left_out_engines_keep_their_reason() -> None:
    by_slot = {m.slot: m for m in load_manifest(KIT / "models.json").left_out}
    for slot, reason in WORKSHOP_OUT.items():
        assert "Workshop decision" in by_slot[slot].why and reason in by_slot[slot].why, slot


def test_the_readmes_model_table_matches_the_manifest() -> None:
    manifest = load_manifest(KIT / "models.json")
    rows = {m.group(1): (m.group(2), m.group(3)) for m in re.finditer(MODEL_ROW, README, re.M)}
    assert {slot: status for slot, (_, status) in rows.items()} == {
        **{m.slot.value: "Pinned" for m in manifest.models},
        **{m.slot.value: "Left out" for m in manifest.left_out},
    }
    for m in (*manifest.models, *manifest.left_out):
        assert rows[m.slot.value][0] == (m.licence or "Not checked"), m.slot


def test_the_readme_keeps_the_double_checked_whisper_hashes_for_the_next_pin() -> None:
    found = {m[0]: m[1:] for m in re.findall(HASH_ROW, README, re.M)}
    assert found == WHISPER_MODEL_BIN


# ---- the Windows scripts -------------------------------------------------------------------------
def test_the_installer_installs_only_hash_pinned_wheels_as_the_owner() -> None:
    code = _code(INSTALL)
    assert "--require-hashes --only-binary=:all:" in code and "requirements-kit.txt" in code
    assert "IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)" in code
    assert "icacls $Dir /inheritance:r" in code
    assert code.count("Yes 'Install it now?'") == 2  # Python and Caddy only with his Y
    assert "-I -m jarvis.localspeech models install" in code
    assert "jarvis-local-speech.pth" in code and "kit-src" in code


def test_the_start_script_uses_the_protocols_ports_and_keeps_the_key_in_the_environment() -> None:
    code = _code(START)
    allowed = re.search(r"ValidateSet\(([0-9, ]+)\)\]\[int\]\$HttpsPort = (\d+)", code)
    assert allowed and {int(x) for x in allowed.group(1).split(",")} == set(ALLOWED_PORTS)
    assert set(ALLOWED_PORTS) == set(config_voice.FUNNEL_PORTS)
    assert int(allowed.group(2)) == p.FUNNEL_PORT
    assert f"$gatePort = {p.GATE_PORT}" in code and f"$serverPort = {p.SERVER_PORT}" in code
    assert "funnel --bg --https=$HttpsPort $gatePort" in code
    assert not re.search(r"funnel[^\n]*(\$serverPort|11437)", code)
    assert "New-Object byte[] 32" in code and "$key.Length -lt 32" in code
    assert (
        "$env:JARVIS_LOCAL_SPEECH_KEY = $key" in code
        and "Remove-Item Env:\\JARVIS_LOCAL_SPEECH_KEY" in code
    )
    for line in code.splitlines():
        if "-ArgumentList" in line:
            assert "$key" not in line


def test_the_start_script_refuses_taken_ports_and_only_closes_its_own_funnel() -> None:
    code = _code(START)
    assert code.index("Test-Port $port") < code.index("Start-Process")
    assert code.index("Test-FunnelTaken $HttpsPort") < code.index("New-Object byte[] 32")
    assert "$funnelOn = $true" in code and code.index("$funnelOn = $true") > code.index(
        "$LASTEXITCODE -ne 0"
    )
    assert "if ($funnelOn) { & tailscale funnel --https=$HttpsPort off" in code
    assert "reset" not in code


def test_the_readme_covers_the_setup_and_what_was_left_out_in_plain_words() -> None:
    text = " ".join(README.split())
    for token in (
        "₹0 a month",
        "install-kit.ps1",
        "start-kit.ps1 -SelfTest",
        "-HttpsPort 443",
        "JARVIS_LOCAL_SPEECH_URL",
        "jarvis-local-speech-key",
        "http://127.0.0.1:11436/v1",
        "delete-recordings",
        "What this kit leaves out",
        "GPL-3.0",
        "Only English listening is pinned",
        "git blob id",
        "encrypted",
    ):
        assert token in text, token
    for text_file in (README, CADDY, INSTALL, START, UNIX.read_text()):
        names = set(re.findall(r"[A-Za-z0-9<>.-]+\.ts\.net", text_file))
        assert names <= {"my-laptop.tail1234.ts.net", "<machine>.<tailnet>.ts.net"}, names


# ---- run start-kit.sh against stubs --------------------------------------------------------------
@pytest.fixture
def stubs(tmp_path: Path) -> dict[str, Path]:
    for port in (p.GATE_PORT, p.SERVER_PORT):
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                pytest.skip(f"port {port} is in use on this machine")
    bin_dir, log = tmp_path / "bin", tmp_path / "log"
    bin_dir.mkdir()
    log.mkdir()

    def stub(path: Path, body: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("#!/usr/bin/env bash\n" + body)
        path.chmod(path.stat().st_mode | stat.S_IEXEC)

    listen = (
        "import socket, time; s = socket.socket(); "
        "s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1); "
        f"s.bind(('127.0.0.1', {p.SERVER_PORT})); s.listen(); time.sleep(20)"
    )
    stub(
        tmp_path / "kit" / "venv" / "bin" / "python",
        'echo "key=$JARVIS_LOCAL_SPEECH_KEY manifest=$JARVIS_SPEECH_KIT_MANIFEST"'
        f' > "{log}/server_env"\n'
        f'echo "args=$*" > "{log}/server_args"\n'
        f'exec "{sys.executable}" -c "{listen}"\n',
    )
    stub(
        bin_dir / "caddy",
        f'echo "key=$JARVIS_LOCAL_SPEECH_KEY" > "{log}/caddy_env"\n'
        f'echo "args=$*" > "{log}/caddy_args"\nexit 0\n',
    )
    stub(
        bin_dir / "tailscale",
        f'echo "$@" >> "{log}/tailscale"\n'
        'if [ "$1 $2" = "funnel status" ]; then\n'
        '  cat "$(dirname "$0")/status" 2>/dev/null\n'
        '  echo "https://my-laptop.tail1234.ts.net:8443 (Funnel on)"; echo "|-- / proxy http://127.0.0.1:11436"\n'
        '  echo "https://my-laptop.tail1234.ts.net:10000 (Funnel on)"; echo "|-- / proxy http://127.0.0.1:11436"\n'
        "fi\nexit 0\n",
    )
    return {"bin": bin_dir, "log": log, "kit": tmp_path / "kit"}


def _run(stubs: dict[str, Path], **env: str) -> subprocess.CompletedProcess[str]:
    base = {
        "PATH": f"{stubs['bin']}:/usr/bin:/bin",
        "HOME": str(stubs["kit"].parent),
        "JARVIS_SPEECH_KIT_DIR": str(stubs["kit"]),
        "JARVIS_SPEECH_KIT_WAIT_S": "10",
    }
    return subprocess.run(
        ["bash", str(UNIX)],
        env={**base, **env},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def test_the_unix_script_is_strict_bash() -> None:
    assert subprocess.run(["bash", "-n", str(UNIX)], check=False).returncode == 0
    text = UNIX.read_text()
    assert (
        text.startswith("#!/usr/bin/env bash")
        and "set -euo pipefail" in text
        and "umask 077" in text
    )


def test_a_run_makes_a_private_key_and_publishes_only_the_gate(stubs: dict[str, Path]) -> None:
    r = _run(stubs)
    assert r.returncode == 0, r.stderr
    key_file = stubs["kit"] / "key"
    key = key_file.read_text()
    assert (
        re.fullmatch(r"[A-Za-z0-9_-]{43}", key) and len(base64.urlsafe_b64decode(key + "=")) == 32
    )
    assert (
        stat.S_IMODE(key_file.stat().st_mode) == 0o600
        and stat.S_IMODE(stubs["kit"].stat().st_mode) == 0o700
    )
    assert (
        "Address: https://my-laptop.tail1234.ts.net:10000" in r.stdout and f"Key: {key}" in r.stdout
    )
    log = stubs["log"]
    assert (log / "server_env").read_text().startswith(f"key={key} manifest={KIT}/models.json")
    assert (log / "server_args").read_text().strip() == "args=-I -m jarvis.localspeech serve"
    assert (log / "caddy_env").read_text().strip() == f"key={key}"
    assert key not in (log / "caddy_args").read_text() + (log / "server_args").read_text()
    ts = (log / "tailscale").read_text()
    assert f"funnel --bg --https={p.FUNNEL_PORT} {p.GATE_PORT}" in ts
    assert str(p.SERVER_PORT) not in ts
    assert f"funnel --https={p.FUNNEL_PORT} off" in ts and "reset" not in ts
    assert "8443" not in ts.replace("funnel status", "")  # the home bridge's port is never used
    again = _run(stubs)
    assert key_file.read_text() == key and f"Key: {key}" in again.stdout


def test_a_funnel_port_held_by_the_home_bridge_is_never_taken(stubs: dict[str, Path]) -> None:
    # R5.2 review: one door each (the bridge 8443, the offline brain 443, the kit 10000)
    (stubs["bin"] / "status").write_text(
        "https://my-laptop.tail1234.ts.net:8443 (Funnel on)\n|-- / proxy http://127.0.0.1:8099\n"
    )
    r = _run(stubs, JARVIS_SPEECH_KIT_HTTPS_PORT="8443")
    assert r.returncode != 0 and "already serves something else" in r.stderr
    assert not (stubs["kit"] / "key").exists() and not (stubs["log"] / "caddy_env").exists()
    r = _run(stubs)  # I1: the kit's default, 10000, leaves the bridge's 8443 alone
    assert r.returncode == 0, r.stderr
    assert "Address: https://my-laptop.tail1234.ts.net:10000" in r.stdout
    assert "funnel --bg --https=10000 11436" in (stubs["log"] / "tailscale").read_text()


def test_a_wrong_port_or_a_missing_program_stops_before_anything_starts(
    stubs: dict[str, Path],
) -> None:
    r = _run(stubs, JARVIS_SPEECH_KIT_HTTPS_PORT="1234")
    assert r.returncode != 0 and "443, 8443 or 10000" in r.stderr
    (stubs["bin"] / "caddy").unlink()
    r = _run(stubs)
    assert r.returncode != 0 and "Missing: caddy" in r.stderr
    assert not (stubs["log"] / "tailscale").exists()
