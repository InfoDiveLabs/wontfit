.PHONY: test lint fmt run showcase demo screenshots build clean

PY ?= python3
UPSTREAM ?= http://localhost:3000
SHOWCASE_PORT ?= 3939

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
	$(PY) -m wontfit --upstream $(UPSTREAM) --open

## Try wontfit in 30 seconds: the Ledgerly showcase site (blocks framing, has planted bugs)
showcase:
	$(PY) examples/showcase/server.py --port $(SHOWCASE_PORT) & echo $$! > .showcase.pid; \
	sleep 0.5; $(PY) -m wontfit --no-config --upstream http://localhost:$(SHOWCASE_PORT) \
	  --pages /,/pricing,/dashboard,/terms --widths se,iphone15,pixel8 --open; \
	kill `cat .showcase.pid`; rm -f .showcase.pid

## Regenerate docs/images (needs a venv with playwright + pillow: see docs/screenshots.py)
screenshots:
	$(PY) docs/screenshots.py

## Start a throwaway upstream that blocks framing, then wontfit against it
demo:
	$(PY) tests/demo_upstream.py --port 3999 & echo $$! > .demo.pid; \
	sleep 0.5; $(PY) -m wontfit --upstream http://localhost:3999 --pages /,/wide --open; \
	kill `cat .demo.pid`; rm -f .demo.pid

## Build sdist and wheel
build:
	$(PY) -m pip install --quiet build && $(PY) -m build

clean:
	rm -rf build dist *.egg-info .ruff_cache shots
	find . -name __pycache__ -type d -exec rm -rf {} +
