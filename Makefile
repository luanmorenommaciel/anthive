.PHONY: help install lint format test test-fast test-e2e test-cov ship clean

PY := .venv/bin/python
PIP := .venv/bin/pip
PYTEST := .venv/bin/pytest

help:
	@echo "anthive — make targets"
	@echo ""
	@echo "  make install     Create .venv and install dev extras"
	@echo "  make lint        Run ruff + black --check"
	@echo "  make format      Apply ruff --fix + black"
	@echo "  make test        Lint + full test suite (unit + integration + e2e) — RELEASE GATE"
	@echo "  make test-fast   Skip e2e tests (fast inner loop)"
	@echo "  make test-e2e    Only e2e tests"
	@echo "  make test-cov    Full suite with coverage report"
	@echo "  make ship        Alias for 'make test' — green = ready to release"
	@echo "  make clean       Remove caches and the venv"

install:
	python3 -m venv .venv
	$(PIP) install --upgrade pip
	$(PIP) install -e ".[dev]"

lint:
	$(PY) -m ruff check anthive/
	$(PY) -m black --check anthive/

format:
	$(PY) -m ruff check --fix anthive/
	$(PY) -m black anthive/

test: lint
	$(PYTEST) anthive/ -v

test-fast:
	$(PYTEST) anthive/ -v -m "not e2e"

test-e2e:
	$(PYTEST) anthive/tests/e2e/ -v

test-cov: lint
	$(PYTEST) anthive/ -v --cov=anthive --cov-report=term-missing --cov-fail-under=70

ship: test
	@echo ""
	@echo "✓ All checks green — anthive is ready to ship."

clean:
	rm -rf .venv .pytest_cache .coverage htmlcov anthive/**/__pycache__ anthive/__pycache__
