PY ?= python3
VENV ?= .venv

.PHONY: setup check quick tasks

setup:
	$(PY) -m venv $(VENV)
	$(VENV)/bin/pip install -e ".[dev]"

check:
	$(VENV)/bin/python -m edgebench.cli gates

quick:
	$(VENV)/bin/python -m edgebench.cli gates --quick

tasks:
	$(VENV)/bin/python -m edgebench.cli tasks
