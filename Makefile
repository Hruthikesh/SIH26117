# YANTRA build/dev entry points. POSIX hosts (Linux, macOS, WSL2).
# On native Windows run the underlying commands directly; they are listed in README.md.

.PHONY: dev server tui test test-py test-ts lint typecheck fmt bundle install-offline demo seal-verify migrate clean

UV ?= uv
PNPM ?= pnpm

dev: ## install everything and run server + TUI (two processes)
	$(UV) sync --all-extras
	$(PNPM) install
	$(PNPM) run gen:types
	$(PNPM) --filter yantra-tui build
	$(UV) run yantra dev

server:
	$(UV) run yantra serve

tui:
	$(PNPM) --filter yantra-tui dev

test: test-py test-ts

test-py:
	$(UV) run pytest -q

test-ts:
	$(PNPM) --filter yantra-tui test

lint:
	$(UV) run ruff check server scripts
	$(UV) run ruff format --check server scripts
	$(PNPM) --filter yantra-tui lint

typecheck:
	$(UV) run mypy
	$(PNPM) --filter yantra-tui typecheck

fmt:
	$(UV) run ruff format server scripts
	$(UV) run ruff check --fix server scripts

migrate:
	$(UV) run alembic -c server/alembic.ini upgrade head

bundle:
	bash scripts/bundle.sh

install-offline:
	bash bundle/install.sh

demo:
	bash scripts/demo.sh

seal-verify:
	$(UV) run yantra seal verify

clean:
	rm -rf .venv node_modules tui/dist web/dist .pytest_cache .mypy_cache .ruff_cache
