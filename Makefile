# One-command workflows. Python >= 3.12 required.
PY ?= python3
VENV := .venv
BIN := $(VENV)/bin

.PHONY: setup test lint fmt dev hooks frontend run eval examples docs
setup: $(BIN)/activate hooks  ## create venv, install deps, install git hooks
$(BIN)/activate: backend/pyproject.toml
	$(PY) -m venv $(VENV)
	$(BIN)/pip install -q --upgrade pip
	$(BIN)/pip install -q -e "backend[dev]"
	touch $(BIN)/activate
hooks:
	$(BIN)/pre-commit install --hook-type pre-commit --hook-type commit-msg --hook-type pre-push
test:  ## LLM-free suite (safety, graph, API) -- the merge-blocking floor
	cd backend && ../$(BIN)/pytest -q
lint:
	$(BIN)/pre-commit run --all-files
fmt:
	cd backend && ../$(BIN)/ruff check --fix . && ../$(BIN)/ruff format .
dev:  ## API on http://localhost:8000
	cd backend && ../$(BIN)/uvicorn app.main:app --reload --port 8000
frontend:  ## build the dashboard into frontend/dist (served by the API)
	cd frontend && npm ci --no-audit --no-fund && npm run build
run: setup frontend  ## one command: install, build, serve on http://localhost:8000
	cd backend && ../$(BIN)/uvicorn app.main:app --port 8000
eval:  ## golden set + gate (real model calls if keys are set in .env, else offline)
	cd backend && set -a && [ -f ../.env ] && . ../.env; set +a; ../$(BIN)/python -m evals.run_evals
examples:  ## regenerate docs/examples.md (offline, reproducible)
	$(BIN)/python scripts/examples.py
docs:  ## rebuild docs/architecture (diagrams + branded HTML) from ARCHITECTURE.md
	$(BIN)/pip install -q markdown && $(BIN)/python docs/architecture/build.py
