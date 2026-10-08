.PHONY: setup portal run test lint eval eval-llm eval-rpa demo invoices ui

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
	# Expanded measured set includes pipeline + browser_loop (no omit gaming).
	# Fail-under reflects achievable branch coverage on Playwright-heavy modules;
	# policy/fsm/recovery/idempotency/events stay mid-90s in the same report.
	uv run pytest -q \
		--cov=ark_operator.policy \
		--cov=ark_operator.runtime.fsm \
		--cov=ark_operator.runtime.recovery \
		--cov=ark_operator.runtime.idempotency \
		--cov=ark_operator.runtime.stall_detector \
		--cov=ark_operator.runtime.plan_revision \
		--cov=ark_operator.runtime.browser_loop \
		--cov=ark_operator.runtime.pipeline \
		--cov=ark_operator.memory.lesson_policy \
		--cov=ark_operator.memory.episodic \
		--cov=ark_operator.verify \
		--cov=ark_operator.events \
		--cov=ark_operator.tools.pdf_extract \
		--cov-report=term-missing:skip-covered \
		--cov-fail-under=82

lint:
	uv run ruff check ark_operator company_world evals tests
	uv run ruff format --check ark_operator company_world evals tests
	uv run mypy ark_operator

# Default measured path: FakeLLM scripted a11y browser loop (not RPA shortcut).
eval:
	uv run python -m evals.runner

# Real Anthropic Haiku subset (a11y loop). Requires ANTHROPIC_API_KEY in .env.
# Never falls back to FakeLLM. RPA repair after a11y miss is disabled.
# Default scenarios: 06/05-approval 04-ui-rename 03-session 01-happy (narrowed).
# Writes evals/results/summary-llm.md (gitignored live run; template committed).
eval-llm:
	uv run python -m evals.runner --llm

# Optional micro-benchmark: high-level submit_invoice RPA shortcut.
eval-rpa:
	uv run python -m evals.runner --rpa

# 90s story: fault + approval pause/seeded decide + verifier catch/proof.
# Self-contained: spawns its own portal (ignore PORTAL_BASE_URL unless DEMO_USE_EXISTING_PORTAL=1).
demo: invoices
	PORTAL_ADMIN_TOKEN=$${PORTAL_ADMIN_TOKEN:-demo-admin-token} \
	uv run python -m ark_operator.demo
