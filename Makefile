.PHONY: setup portal run test lint eval demo invoices ui

PORTAL_PORT ?= 8765
OPERATOR_PORT ?= 8877

setup:
	uv sync
	uv run python -m company_world.scripts.make_invoices
	uv run playwright install chromium

invoices:
	uv run python -m company_world.scripts.make_invoices

portal: invoices
	uv run python -m company_world.portal

ui:
	PORTAL_BASE_URL=http://127.0.0.1:$(PORTAL_PORT) \
	uv run uvicorn ark_operator.api.app:app --host 127.0.0.1 --port $(OPERATOR_PORT)

run:
	uv run operator run "Process this month's pending vendor invoices." --auto-approve

test:
	uv run pytest -q \
		--cov=ark_operator.policy \
		--cov=ark_operator.runtime.fsm \
		--cov=ark_operator.runtime.recovery \
		--cov=ark_operator.runtime.idempotency \
		--cov=ark_operator.verify \
		--cov=ark_operator.events \
		--cov-report=term-missing:skip-covered \
		--cov-fail-under=89

lint:
	uv run ruff check ark_operator company_world evals tests
	uv run ruff format --check ark_operator company_world evals tests
	uv run mypy ark_operator

eval:
	uv run python -m evals.runner

demo: invoices
	@echo "Demo: ensure portal is running (make portal), then:"
	@echo "  1) Open Operator UI: make ui  -> http://127.0.0.1:$(OPERATOR_PORT)"
	@echo "  2) Or CLI: make run"
	@echo "Running headless CLI demo subset..."
	PORTAL_BASE_URL=http://127.0.0.1:$(PORTAL_PORT) \
	uv run operator run "Process this month's pending vendor invoices." --auto-approve --only INV-1001,INV-1008,INV-1010
