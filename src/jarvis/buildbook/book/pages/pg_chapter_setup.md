---
page: pg_chapter_setup
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "Makefile": "3c446b64c5b9cb98"
  "docker-compose.yml": "a9301e2740ef32ca"
  "pyproject.toml": "bc1af1b3158d2ba0"
  "src/jarvis/api/app.py": "51eaf37fbe6a89cf"
  "src/jarvis/api/auth.py": "02a9e121c2585fd8"
  "src/jarvis/api/body.py": "94feeb1db871c289"
  "src/jarvis/api/console.py": "00a751a9f79bad8f"
  "src/jarvis/api/feature_wiring.py": "473760847cb35d03"
  "src/jarvis/api/home_wiring.py": "47912d10ccd3e249"
  "src/jarvis/api/identity.py": "4b025a7710b59c4b"
  "src/jarvis/api/personal.py": "7a9aa32e08b7d084"
  "src/jarvis/api/r11_wiring.py": "4cfa5b25282b147c"
  "src/jarvis/api/r4_wiring.py": "379192618b74836f"
  "src/jarvis/api/r6_wiring.py": "793c1b46ad0c7c74"
  "src/jarvis/api/ratelimit.py": "cb57d8dab93e8640"
  "src/jarvis/api/routes.py": "582978dc4ebc2995"
  "src/jarvis/api/selfcheck_wiring.py": "fb7336391ffa3727"
  "src/jarvis/api/startup_log.py": "4ba9e18096e253e1"
  "src/jarvis/api/static/console-3d-scenes.js": "80d2691e8bb110de"
  "src/jarvis/api/static/console-3d.js": "b590fd5947ccb313"
  "src/jarvis/api/static/console-deck.js": "856dae35d81cdbc3"
  "src/jarvis/api/static/console-dock.js": "0798faf0a39ad778"
  "src/jarvis/api/static/console-fx.js": "bb9dd7f373411a5f"
  "src/jarvis/api/static/console-helpers.js": "38c9179fa5cd2d23"
  "src/jarvis/api/static/console-text.js": "be5a5239bbffae37"
  "src/jarvis/api/static/console.css": "6a8f96e9bcd21971"
  "src/jarvis/api/static/console.html": "9f4c0c68f45e46fe"
  "src/jarvis/api/static/console.js": "351db845674caa00"
  "src/jarvis/cli.py": "ba5cceebcf16d9d0"
  "src/jarvis/config.py": "0f90cbe2c5f58fde"
---
## In plain words
This chapter is about running JARVIS on a computer of your own, to try something out or for an engineer to work on it, without touching the live JARVIS. You install it from the project folder, give it settings in a small file, and start it; the same console then opens in a browser on that machine. Set the brain to the built-in test brain and it answers without any AI key, so you see every screen without spending a rupee. With a Claude key it thinks just as the live one does.

## Example (made up)
Kabir, an engineer friend helping with JARVIS, copies the project to his laptop on a Saturday. He runs make install, writes a .env file that picks the mock brain and a bearer token, and runs make serve. At localhost port 8000 the console opens and asks for the token; the test brain answers each message with a fixed reply. He runs make test, and about 5 minutes later every test has passed. Nothing he did reached the live JARVIS or its data.

## How it works
`pyproject.toml` describes the package and the libraries it needs; the Makefile's install step installs it with the development tools, and its serve and chat steps start the server or a terminal chat. `src/jarvis/cli.py` provides the jarvis command: chat talks to the brain in-process with no server, and serve starts the web server. `get_settings` reads every setting from the environment or a .env file (`src/jarvis/config.py`). `env` is {{fact:settings.env}} unless you say otherwise, which relaxes rules meant for production, and that development mode refuses to start on Cloud Run (`Settings`). `llm_backend` picks the brain from `LLMBackend`: the Claude brain needs `anthropic_api_key`, while the mock brain gives fixed answers and needs no key. `session_backend` decides where conversations live, one of `SessionBackend`: in memory by default, in Redis under Docker, in Firestore on Cloud Run. `docker-compose.yml` starts the server in a container beside a Redis database that keeps conversations across restarts. `auth_mode` decides how you sign in, one of `AuthMode`: token mode accepts only the bearer token in `api_token`, and Google mode needs the Google sign-in settings (`src/jarvis/api/auth.py`). `create_app` builds the same server as the cloud one, and a feature whose settings or keys are missing stays off (`src/jarvis/api/app.py`). `src/jarvis/api/console.py` serves the same console page, `src/jarvis/api/static/console.html`, from your machine. `log_up` writes one "jarvis up" line naming which parts started, never a key or an address (`src/jarvis/api/startup_log.py`).

## What it costs
Nothing with the mock brain: it runs on your own computer and calls no outside service (`src/jarvis/config.py`). With a Claude key, each reply costs the same tokens as on the live JARVIS, counted against the monthly limit (`src/jarvis/cli.py`).

## When it fails
With the Claude brain chosen and no key, start-up stops with a line naming the missing setting (`src/jarvis/config.py`). Outside development mode, a missing bearer token stops it too (`Settings`). An unknown brain asked for in the terminal chat stops with the list of brains you have set up (`src/jarvis/cli.py`).
