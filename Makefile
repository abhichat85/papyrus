.PHONY: help install test lint fmt fixtures samples serve web docker clean

help:
	@grep -E '^[a-z-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

install:  ## Create the venv and install the engine with API + dev extras
	uv venv --python 3.11
	uv pip install -e ".[api,dev]"

test:  ## Run the test suite
	.venv/bin/python -m pytest

lint:  ## Lint
	.venv/bin/ruff check src tests scripts

fmt:  ## Format
	.venv/bin/ruff format src tests scripts
	.venv/bin/ruff check src tests scripts --fix

fixtures:  ## Rebuild the binary test fixtures
	.venv/bin/python tests/make_fixtures.py

samples:  ## Rebuild the demo documents served by the web app
	.venv/bin/python scripts/make_samples.py

serve:  ## Run the HTTP API on :8787
	.venv/bin/papyrus serve --port 8787 --reload

web:  ## Run the web app on :3473 (needs `make serve` in another shell)
	npm --prefix web run dev

docker:  ## Build and run everything in containers
	docker compose up --build

clean:
	rm -rf .pytest_cache .ruff_cache .coverage htmlcov dist build
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
