.PHONY: install test lint type eval eval-mock serve chat

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
	python evals/phase0/run.py --mock

serve:
	jarvis serve --reload

chat:
	jarvis chat --stream
