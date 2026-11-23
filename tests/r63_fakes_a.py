# tests/r63_fakes_a.py -- R6.3 part A's fakes (docs/plans/r6-3-book-content.md D2, D3). Imported
# bare (`from r63_fakes_a import ...`). A small repository for the fact pack's scanners: routers
# named every way the code names them, constants in every shape H5 counts (and the ones it
# doesn't), settings with bounds, collections in each naming idiom, a console with two panels and
# the show, and I0's three-card guide (r63_fakes.GUIDE) with a fourth card added on demand.
from __future__ import annotations

from pathlib import Path

from r63_fakes import FIXTURE_FILES, GUIDE

from jarvis.buildbook.gen.modules import Module
from jarvis.buildbook.gen.repo import Repo

SHA = "a6" * 20
COMMITTED = "2026-11-24T03:30:00+00:00"  # 09:00 IST
DEMO = (Module("demo", "The demo", ("C01", "C02", "C03")),)
ROUTES_PY = '''"""Routers in every shape the scan must read."""
from fastapi import APIRouter, FastAPI

from jarvis.demo.paths import BASE
from jarvis.buildbook.writer.http import ROUTES

PREFIX = "/v1/demo"
router = APIRouter(prefix=PREFIX)
public = APIRouter(prefix=f"{BASE}/public")
hook_router = APIRouter()
looped = APIRouter(prefix="/v1/book/writer")


@router.get("/items")
async def items() -> list[str]:
    return []


@public.api_route("/ping", methods=["GET", "POST"])
async def ping() -> str:
    return "pong"


@hook_router.websocket("/ws")
async def ws() -> None:
    return None


def make() -> APIRouter:
    inner = APIRouter(prefix="/v1/inner")

    @inner.delete("/{item_id}")
    async def gone(item_id: str) -> None:
        return None

    return inner


def app() -> FastAPI:
    a = FastAPI()
    a.add_api_route("/healthz", items, methods=["HEAD"])

    @a.post("/v1/hook")
    async def hook() -> None:
        return None

    return a


router.add_api_route("/added", items)
for _method, _path, *_rest in ROUTES:
    if _path.startswith("/v1/book/writer"):
        looped.add_api_route(_path.removeprefix("/v1/book/writer"), items, methods=[_method])
'''
HTTP_PY = """_W = "/v1/book/writer"
ROUTES = (
    ("GET", _W, "B"),
    ("POST", f"{_W}/trial", "B"),
    ("GET", "/v1/book/pages", "B"),
)
"""
CONSTANTS_PY = '''"""Constants in every shape."""
MAX_TRIES = 3
BREAKER_S: float = 120.0
WINDOW_S = 15 * 60
OFFSET = -2
HOLD_S, COUNTDOWN_S = 2, 5
_PRIVATE_CAP = 2 ** 10
RATIO = 1 / 4
FLAG = True
NAME = "not a number"
lower = 7
BAD = 1 / 0
CALLED = int("5")
HUGE = 10 ** 400


def f() -> int:
    INSIDE = 9
    return INSIDE
'''
CONFIG_PY = """from typing import Literal

from pydantic import Field, SecretStr


class Settings:
    demo_limit: int = Field(default=5, ge=1, le=10)
    model_balanced: str = Field(default="claude-sonnet-5-5", description="Everyday chat")
    region: Literal["us", "eu"] = "us"
    api_key: SecretStr | None = None
    ratio: float = Field(0.5, ge=0.0, le=1.0)
    hosts: tuple[str, ...] = ("a", "b")
    home_url: str = "https://owner.example.org/x"
    voice_price_chirp3_hd_usd_per_m: float = 30.0
    voice_price_studio_usd_per_m: float = 160.0
    voice_price_stt_usd_per_min: float = 0.016
"""
STORES_PY = """COLLECTION = "demo_notes"


def path(p: str) -> str:
    return f"{p}demo_drafts/x" + _path("demo_runs")


def _path(name: str) -> str:
    return name


class Store:
    def __init__(self, db, prefix: str) -> None:
        self._prefix = prefix
        self.col = db.collection(f"{self._prefix}demo_items")
        self.other = f"{self._prefix}demo_votes"
"""
CONSOLE_HTML = """<!doctype html>
<section id="p-chat" data-panel="chat" hidden><h2 id="t-chat">Conversation</h2></section>
<section id="p-demo" data-panel="demo" hidden><h2 id="t-demo">Demo panel</h2></section>
"""
BOOK_HTML = """<!doctype html>
<script src="/static/console-fx.js"></script>
<script src="/static/console-book-show.js"></script>
"""
EXTRA_FILES: dict[str, str] = {
    "src/jarvis/demo/routes.py": ROUTES_PY,
    "src/jarvis/demo/paths.py": 'BASE = "/v1/base"\n',
    "src/jarvis/demo/consts.py": CONSTANTS_PY,
    "src/jarvis/demo/stores.py": STORES_PY,
    "src/jarvis/buildbook/writer/http.py": HTTP_PY,
    "src/jarvis/config.py": CONFIG_PY,
    "src/jarvis/api/static/console.html": CONSOLE_HTML,
    "src/jarvis/api/static/book.html": BOOK_HTML,
    "src/jarvis/api/static/console-fx.js": "export const fx = 1;\n",
    "src/jarvis/api/static/console-book-show.js": "// the show\n",
    "src/jarvis/api/static/console-demo-panel.js": "// the demo panel\n",
    "deploy/cloudrun.sh": (
        'REGION="${REGION:-asia-south1}"\n'
        "gcloud run deploy x --min-instances 0 --max-instances 1 \\\n"
        "  --memory 512Mi --cpu 1 --timeout 300\n"
    ),
}
C74 = """#### C74 · Demo extra

| Field | Value |
|---|---|
| Name | Demo extra |
| What it does | A new part. |
| Where in the code | `src/jarvis/demo/` |
| Outside services | Telegram (alerts) and Firestore |
| Since | R6.4 |

"""


# D2b: the technology inventory's five sources, each with what the scan must keep and leave
INVENTORY_FILES: dict[str, str] = {
    "android/gradle/libs.versions.toml": (
        "# Libraries (Part E): all Apache 2.0, exact versions only.\n"
        '[versions]\nagp = "9.5.1"\nkotlin = "2.4.10"\nandroidx-core = "1.17.0"\n\n'
        "[libraries]\n"
        'androidx-core = { module = "androidx.core:core", version.ref = "androidx-core" }\n'
        'health = { module = "androidx.health.connect:connect-client", version = "1.1.0" }\n\n'
        "[plugins]\n"
        'android-application = { id = "com.android.application", version.ref = "agp" }\n'
        'kotlin-jvm = { id = "org.jetbrains.kotlin.jvm", version.ref = "kotlin" }\n'
    ),
    "deploy/home/docker-compose.yml": (
        "services:\n  mosquitto:\n    image: ${MOSQUITTO_IMAGE:-eclipse-mosquitto:2.0.20}\n"
        "  frigate:\n    image: ${FRIGATE_IMAGE:-ghcr.io/example/frigate:0.17.2}\n"
        "  bridge:\n    image: jarvis-home-bridge:local\n"
    ),
    "deploy/home/bridge-requirements.txt": (
        "# MQTT for the camera: aiomqtt 2.5.1 (BSD-3-Clause) and paho-mqtt 2.1.0\n"
        "# (EPL-2.0 OR BSD-3-Clause). Not in the cloud image. opencv-python-headless 4.12.0.88\n"
        "# (OpenCV: Apache-2.0; the packaging: MIT): a note, not a licence expression.\n"
        "aiomqtt==2.5.1 \\\n    --hash=sha256:00\n"
        "fastapi==0.115.0 \\\n    --hash=sha256:11\n"
        "paho-mqtt==2.1.0 \\\n    --hash=sha256:22\n"
        "opencv-python-headless==4.12.0.88 \\\n    --hash=sha256:33\n"
    ),
    "requirements.lock": "fastapi==0.115.0 \\\n    --hash=sha256:44\n",
    "pyproject.toml": (
        '[project]\nname = "jarvis"\nrequires-python = ">=3.11"\n'
        'dependencies = ["fastapi>=0.115"]\n'
        '\n[project.optional-dependencies]\ndev = ["pytest>=8", "ruff>=0.5"]\n'
        'home = ["aiomqtt==2.5.1"]\n'
    ),
    "tools/markdy/package-lock.json": (
        '{"packages": {"": {"devDependencies": {"@markdy/cli": "1.5.7"}},'
        ' "node_modules/@markdy/cli": {"version": "1.5.7", "license": "MIT", "dev": true},'
        ' "node_modules/@markdy/core": {"version": "1.5.7", "license": "MIT", "dev": true}}}\n'
    ),
}


def write_files(root: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8")
    return root


def repo_of(root: Path, files: dict[str, str]) -> Repo:
    return Repo.from_dir(write_files(root, files), sha=SHA, committed_at=COMMITTED)


def i0_repo(root: Path) -> Repo:
    """I0's fixture repository (r63_fakes.FIXTURE_FILES) exactly."""
    return repo_of(root, dict(FIXTURE_FILES))


def a_repo(root: Path, *, c74: bool = False) -> Repo:
    """I0's fixture with part A's extra files; `c74` adds a fourth card to the guide."""
    files = {**FIXTURE_FILES, **EXTRA_FILES}
    if c74:
        guide = GUIDE.replace("\n## 11. Roadmap", "\n" + C74 + "## 11. Roadmap")
        files["docs/architecture/JARVIS-Architecture.md"] = guide
    return repo_of(root, files)


__all__ = [
    "C74",
    "COMMITTED",
    "DEMO",
    "EXTRA_FILES",
    "INVENTORY_FILES",
    "SHA",
    "a_repo",
    "i0_repo",
    "repo_of",
    "write_files",
]
