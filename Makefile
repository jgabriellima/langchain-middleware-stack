# ─────────────────────────────────────────────────────────────────────────────
# langchain-middleware-stack — developer Makefile
#
# Requires: uv  (https://docs.astral.sh/uv/)
# Usage:
#   make setup       create .venv and install all deps
#   make notebook    launch JupyterLab with the demo notebook
#   make landing     serve docs/ (GitHub Pages preview) on localhost
#   make test        run the test suite
#   make publish-dry preview release (changelog + semver)
#   make publish     full PyPI + GitHub release (needs CONFIRM=yes)
#   make help        list all targets
# ─────────────────────────────────────────────────────────────────────────────
.DEFAULT_GOAL := help

VENV         := .venv
PYTHON       := $(VENV)/bin/python
NOTEBOOK     := notebooks/deep-agents-middleware.ipynb
LANDING_PORT ?= 8765

# ── Phony targets ─────────────────────────────────────────────────────────────
.PHONY: help setup test lint notebook landing run-notebook clean clean-all publish publish-dry

# ── Help ──────────────────────────────────────────────────────────────────────
help: ## Show this help
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / \
	    {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

# ── Environment setup ─────────────────────────────────────────────────────────
setup: ## Create .venv and install package + dev + notebook extras
	uv venv $(VENV)
	uv pip install --python $(PYTHON) -e ".[dev,notebook]"
	@echo ""
	@echo "  ✓  .venv ready"
	@echo "  →  activate :  source $(VENV)/bin/activate"
	@echo "  →  notebook :  make notebook"

# ── Tests ─────────────────────────────────────────────────────────────────────
test: ## Run the full test suite
	$(PYTHON) -m pytest tests/ -v

# ── Lint ──────────────────────────────────────────────────────────────────────
lint: ## Run ruff on the package source
	$(PYTHON) -m ruff check langchain_middleware_stack/

# ── Notebook ──────────────────────────────────────────────────────────────────
# JupyterLab blocks `../` in Markdown image URLs. Symlink docs images under notebooks/
# so paths stay inside the notebook directory (see notebooks/docs_assets_images).
notebooks/docs_assets_images:
	@cd notebooks && ln -sfn ../docs/assets/images docs_assets_images

notebook: notebooks/docs_assets_images ## Launch JupyterLab with the demo notebook
	$(VENV)/bin/jupyter lab $(NOTEBOOK)

run-notebook: ## Execute the notebook in-place without a browser (CI-safe)
	$(VENV)/bin/jupyter nbconvert \
	    --to notebook \
	    --execute \
	    --inplace \
	    --ExecutePreprocessor.timeout=120 \
	    $(NOTEBOOK)
	@echo "  ✓  $(NOTEBOOK) executed and saved in place"

# ── Release / PyPI ───────────────────────────────────────────────────────────
# Requires: .venv + .[dev], git, gh (unless SKIP_GH=1), PyPI creds for twine (unless SKIP_PYPI=1).
# Preview:  make publish-dry
# Ship:     make publish CONFIRM=yes [BUMP=auto|major|minor|patch|none]
publish-dry: ## Preview changelog + semver bump (DRY_RUN=1; no git/PyPI/GitHub)
	@test -x $(PYTHON) || (echo "Run make setup first."; exit 1)
	@DRY_RUN=1 $(PYTHON) scripts/release_publish.py

publish: ## Bump version, test, build, twine check, push, PyPI, GitHub (needs CONFIRM=yes)
	@test -x $(PYTHON) || (echo "Run make setup first."; exit 1)
	@CONFIRM=$(CONFIRM) BUMP=$(BUMP) SKIP_TESTS=$(SKIP_TESTS) SKIP_PYPI=$(SKIP_PYPI) SKIP_GH=$(SKIP_GH) $(PYTHON) scripts/release_publish.py

# ── Clean ─────────────────────────────────────────────────────────────────────
clean: ## Remove build artefacts (keeps .venv)
	rm -rf dist/ build/ *.egg-info langchain_middleware_stack.egg-info
	find . -path "./.venv" -prune -o -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -path "./.venv" -prune -o -name "*.pyc"       -exec rm -f  {} + 2>/dev/null || true

clean-all: clean ## Remove .venv and all build artefacts
	rm -rf $(VENV)
