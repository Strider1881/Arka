# Operator

An autonomous AI employee that turns a short company request into **completed** work,
proves it with independent verification, and only interrupts a human when policy or
ambiguity requires it.

> **Pitch:** An employee that finishes the job, proves it, and only interrupts you when it truly matters.

## The 90-second story

1. Type: `Process this month's pending vendor invoices.`
2. Operator understands the goal, loads AcmeCorp policy, extracts inbox PDFs, and works the procurement portal via the **a11y observe→act browser loop**.
3. INV-1003 (over $5k) pauses for one approval card (summary + policy + risk). Approve → resume.
4. Injected faults (session expiry / renamed Submit button) recover; INV-1010 injection is recorded, not obeyed.
5. Proof screen: per-invoice outcomes + independent **Verified** panel (API + hard browser scrape). Details shows tokens/cost/timeline.

Reproduce headlessly: `make demo` (spawns its own portal — fault + approval pause + verifier sabotage + proof). Interactive UI: `make portal` + `make ui`. Full script: [docs/DEMO.md](docs/DEMO.md).

## Measured path (honest)

| Path | When | Browser writes |
|------|------|----------------|
| **a11y loop (default)** | `make eval`, CLI/UI default | Observe compact a11y tree → LLM picks **one** action → tool → repeat until postcondition (`scripted_browser_step` under FakeLLM) |
| **RPA shortcut (optional)** | `make eval-rpa` / `--no-browser-loop` | High-level `submit_invoice` (still real Playwright) — micro-benchmark / repair only |

Policy decisions and verification are **never** FakeLLM. DesktopTool remains **STUB**.

**Runtime:** `InvoicePipeline` owns phases end-to-end (FSM). `Orchestrator` allocates `run_id` only.

## Quickstart

```bash
cp .env.example .env
# Set PORTAL_OPERATOR_PASSWORD (and optional PORTAL_ADMIN_TOKEN, ANTHROPIC_API_KEY)
make setup
make lint && make test && make eval   # measured path = a11y loop
make demo                              # self-contained 90s story (own portal)
make portal                            # terminal A — http://127.0.0.1:8765
make ui                                # terminal B — http://127.0.0.1:8877
```

Never commit `.env`. Portal `/admin/faults` requires auth (session or `PORTAL_ADMIN_TOKEN`). Passwords are PBKDF2-hashed. `make demo` does not need a pre-started portal.

### CLI

```bash
uv run operator run "Process this month's pending vendor invoices."
uv run operator approve <run_id> --step INV-1003          # SPEC shape
uv run operator status <run_id>
uv run operator replay <run_id>
uv run operator eval                                      # a11y loop (default)
```

## Eval results

Latest `make eval` (**a11y loop** measured path) → [evals/results/summary.md](evals/results/summary.md):

| Aggregate | Result |
|-----------|--------|
| task_success | **12/12** |
| false_success_rate | **0.00** |
| unsafe_actions | **0** |
| recoveries (02 / 03 / 04) | **5 / 1 / 1** |

| Scenario | Intent |
|----------|--------|
| 01-happy | No faults (all 12 invoices) |
| 02-latency-flaky | flaky_500 recoveries |
| 03-session-expiry | Mid-run session invalidation |
| 04-ui-rename | Label miss → stable id re-resolve |
| 05 / 06 | Approval granted / rejected |
| 07 / 08 | Duplicate / amount mismatch |
| 09 / 10 | Blocked vendor / PDF injection |
| 11 / 12 | Missing PO via **CLARIFY** / crash-resume |

## Architecture

Package: **`ark_operator/`** (SPEC `operator/` renamed — stdlib clash). Event-sourced FSM, irreversible ledger, independent Playwright+API verifier (browser scrape hard-fails submit-class misses), HTMX+SSE UI (Handoff → Work → Proof + Details).

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- [docs/DECISIONS.md](docs/DECISIONS.md)
- [docs/DEMO.md](docs/DEMO.md)
- [docs/SPEC.md](docs/SPEC.md)

## Limitations (honest)

- Invoice **decisions** remain deterministic `PolicyEngine` (LLM owns understand/plan/browser_step/invoice_extract structure).
- DesktopTool **STUB** — no general computer-use / vision fallback.
- Full 12-invoice **real-Haiku** browser eval every CI run is cost-prohibitive; FakeLLM a11y loop + keyed Haiku AC cover the bar.
- Repair after a hard a11y miss may use the RPA shortcut once; the measured first pass is the loop.
- Multi-tenant SaaS / embeddings-required memory — explicit non-goals.
