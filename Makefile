.PHONY: setup portal run test lint eval demo invoices

setup:
	uv sync
	uv run python -m company_world.scripts.make_invoices

invoices:
	uv run python -m company_world.scripts.make_invoices

portal: invoices
	uv run python -m company_world.portal

run:
	@echo "STUB: operator run not implemented yet (P2+)."

test:
	uv run pytest -q

lint:
	uv run ruff check ark_operator company_world evals tests
	uv run ruff format --check ark_operator company_world evals tests
	uv run mypy ark_operator

eval:
	@echo "STUB: eval runner not implemented yet (P10)."

demo:
	@echo "STUB: demo script not implemented yet (P10)."
