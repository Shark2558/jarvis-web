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
# Needs: pip install playwright==1.63.0 && playwright install --with-deps chromium
browser-test:
	JARVIS_BROWSER_TESTS=1 pytest -q tests/browser -m browser

# Regenerate the hash-locked dependencies the Docker image installs from: runtime deps from
# pyproject.toml plus the build toolchain (pip, setuptools, wheel) from requirements-build.in.
# Run after any change to either (same Python as the image: 3.12).
lock:
	pip install -q pip-tools
	pip-compile --generate-hashes --strip-extras --allow-unsafe -o requirements.lock \
		pyproject.toml requirements-build.in
