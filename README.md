# Operator

An autonomous AI employee that turns a short company request into **completed** work,
proves it with independent verification, and only interrupts a human when policy or
ambiguity requires it.

> **Pitch:** An employee that finishes the job, proves it, and only interrupts you when it truly matters.

## Status

**Phase 1 (company world) complete.** Portal, seed data, 12 invoice PDFs, knowledge base,
expected outcomes, and fault injection are in place. Operator runtime / UI / evals are still STUB.

Demo GIF/video: *not available yet* (P10).

## The 90-second story (target)

1. Type: `Process this month's pending vendor invoices.`
2. Operator understands, plans, and works through AcmeCorp Procure (browser + PDFs + policy).
3. One approval card when policy requires it; then a one-screen proof report with verifier checks.

## Quickstart

```bash
# Requires Python 3.12+ and uv (https://docs.astral.sh/uv/)
cp .env.example .env   # set PORTAL_OPERATOR_PASSWORD / ANTHROPIC_API_KEY when needed
make setup             # uv sync
make lint              # ruff + mypy (strict on operator/)
make test              # pytest
```

| Target | Status |
|--------|--------|
| `make setup` | Works (also generates invoice PDFs) |
| `make lint` | Works |
| `make test` | Works |
| `make invoices` | Generates 12 PDFs into `company_world/inbox/` |
| `make portal` | Serves AcmeCorp Procure at http://127.0.0.1:8765 |
| `make run` | STUB (P2+) |
| `make eval` | STUB (P10) |
| `make demo` | STUB (P10) |

### Portal quickstart

```bash
cp .env.example .env   # set PORTAL_OPERATOR_PASSWORD
make portal            # regenerates PDFs, then serves on :8765
# Login: operator@acmecorp.test / $PORTAL_OPERATOR_PASSWORD
# Manager: priya.nair@acmecorp.test / $PORTAL_MANAGER_PASSWORD
```

CLI placeholder: `uv run operator --help` (subcommands print STUB until wired).

## Layout

See [docs/SPEC.md](docs/SPEC.md) §5. Package roots: `ark_operator/` (SPEC’s `operator/` renamed — stdlib clash; see [DECISIONS.md](docs/DECISIONS.md)), `company_world/`, `evals/`, `tests/`.

## Docs

- [SPEC.md](docs/SPEC.md) — source of truth
- [DECISIONS.md](docs/DECISIONS.md) — agreed defaults and silent-spec choices
- [ARCHITECTURE.md](docs/ARCHITECTURE.md) — STUB until P10
- [DEMO.md](docs/DEMO.md) — STUB until P10

## Design decisions (summary)

HTMX + SSE UI; stdlib sqlite3; custom backoff; `PORTAL_OPERATOR_PASSWORD`; 12 POs (PO-501…512);
session expiry default N=5. Details in [DECISIONS.md](docs/DECISIONS.md).

## Limitations / next steps

- No operator runtime, browser tool, LLM loop, or Operator UI yet.
- Next phase (P2): domain models, event store, state machine, FakeLLM, budgets, stall detector.
