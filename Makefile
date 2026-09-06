.PHONY: test lint fmt run demo build clean

PY ?= python3
UPSTREAM ?= http://localhost:3000

## Run the unit tests (standard library unittest, no extras needed)
test:
	$(PY) -m unittest -v

## Lint with ruff if available (never required)
lint:
	@if command -v ruff >/dev/null 2>&1; then ruff check . && ruff format --check .; \
	elif command -v uvx >/dev/null 2>&1; then uvx ruff check . && uvx ruff format --check .; \
	else echo "ruff not installed; skipping lint (pip install ruff)"; fi

## Auto-fix lint and formatting
fmt:
	@if command -v ruff >/dev/null 2>&1; then ruff check --fix . && ruff format .; else uvx ruff check --fix . && uvx ruff format .; fi

## Run the proxy against $(UPSTREAM) and open the harness
run:
	$(PY) -m phoneframes --upstream $(UPSTREAM) --open

## Start a throwaway upstream that blocks framing, then phoneframes against it
demo:
	$(PY) tests/demo_upstream.py --port 3999 & echo $$! > .demo.pid; \
	sleep 0.5; $(PY) -m phoneframes --upstream http://localhost:3999 --pages /,/wide --open; \
	kill `cat .demo.pid`; rm -f .demo.pid

## Build sdist and wheel
build:
	$(PY) -m pip install --quiet build && $(PY) -m build

clean:
	rm -rf build dist *.egg-info .ruff_cache shots
	find . -name __pycache__ -type d -exec rm -rf {} +
