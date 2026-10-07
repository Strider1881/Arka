# Operator

An autonomous AI employee that turns a short company request into **completed** work,
proves it with independent verification, and only interrupts a human when policy or
ambiguity requires it.

> **Pitch:** An employee that finishes the job, proves it, and only interrupts you when it truly matters.

## Status

**Phase 0 (scaffold) complete.** Later phases (company portal, runtime, tools, UI, evals)
are not implemented yet. Targets marked STUB print a clear message — nothing is silently faked.

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
| `make setup` | Works |
| `make lint` | Works |
| `make test` | Works |
| `make portal` | STUB (P1) |
| `make run` | STUB (P2+) |
| `make eval` | STUB (P10) |
| `make demo` | STUB (P10) |

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

- No portal, PDFs, runtime, or LLM calls yet — scaffold and tooling only.
- Next phase (P1): company world portal, seed data, invoice PDFs, knowledge base, fault injection.
