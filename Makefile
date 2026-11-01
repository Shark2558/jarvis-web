.PHONY: install test lint type eval eval-mock serve chat browser-test lock

install:
	pip install -e ".[dev]"

test:
	pytest -q

lint:
	ruff check src tests evals

type:
	mypy src

eval:
	python evals/phase0/run.py

eval-mock:
	python evals/run_all_mock.py

serve:
	jarvis serve --reload

chat:
	jarvis chat --stream

# Playwright smoke tests against the real console in headless Chromium (CI `browser` job).
# Needs: pip install playwright && playwright install --with-deps chromium
browser-test:
	JARVIS_BROWSER_TESTS=1 pytest -q tests/browser -m browser

# Regenerate the hash-locked runtime dependencies the Docker image installs from.
# Run after any change to [project].dependencies in pyproject.toml (same Python as the image).
lock:
	pip install -q pip-tools
	pip-compile --generate-hashes --strip-extras --allow-unsafe -o requirements.lock pyproject.toml
