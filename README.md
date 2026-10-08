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

## Measured paths (honest dual track)

Two eval targets — do not conflate them:

| Target | LLM | Browser path | What it proves |
|--------|-----|--------------|----------------|
| **`make eval`** | FakeLLM (scripted) | a11y loop (`scripted_browser_step`) | Deterministic CI: policy + portal + verifier + recovery wiring (12/12) |
| **`make eval-llm`** | Real Anthropic Haiku (`ANTHROPIC_API_KEY`, `OPERATOR_MODEL`) | a11y loop (model chooses actions) | Same subset under a real model; **no FakeLLM fallback**; RPA repair disabled |

| Path | When | Browser writes |
|------|------|----------------|
| **a11y loop (default)** | `make eval` / `make eval-llm`, CLI/UI default | Observe compact a11y tree → LLM picks **one** action → tool → repeat until postcondition |
| **RPA shortcut (optional)** | `make eval-rpa` / `--no-browser-loop` | High-level `submit_invoice` (still real Playwright) — micro-benchmark; FakeLLM CI may still repair via RPA after an a11y miss — **not** on `eval-llm` |

Policy decisions and verification are **never** FakeLLM. DesktopTool remains **STUB**.

**Runtime:** `InvoicePipeline` owns phases end-to-end (FSM). `Orchestrator` allocates `run_id` only.

## Quickstart

```bash
cp .env.example .env
# Set PORTAL_OPERATOR_PASSWORD (and optional PORTAL_ADMIN_TOKEN, ANTHROPIC_API_KEY)
make setup
make lint && make test && make eval   # FakeLLM CI path (deterministic)
make eval-llm                          # real Haiku subset (needs ANTHROPIC_API_KEY)
make demo                              # self-contained 90s story (own portal)
make portal                            # terminal A — http://127.0.0.1:8765
make ui                                # terminal B — http://127.0.0.1:8877
```

Never commit `.env`. Portal `/admin/faults` requires auth (session or `PORTAL_ADMIN_TOKEN`). Passwords are PBKDF2-hashed. `make demo` does not need a pre-started portal. `make eval-llm` exits nonzero if the key is missing — it never silently uses FakeLLM.

### CLI

```bash
uv run operator run "Process this month's pending vendor invoices."
uv run operator approve <run_id> --step INV-1003          # SPEC shape
uv run operator status <run_id>
uv run operator replay <run_id>
uv run operator eval                                      # FakeLLM a11y loop
uv run operator eval --llm                                # real Haiku subset
```

## Eval results

### FakeLLM CI (`make eval`)

Latest run → [evals/results/summary.md](evals/results/summary.md):

| Aggregate | Result |
|-----------|--------|
| task_success | **12/12** |
| false_success_rate | **0.00** |
| unsafe_actions | **0** |
| recoveries (02 / 03 / 04) | **5 / 1 / 1** |
| LLM | FakeLLM (scripted a11y steps) |

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

### Real Haiku (`make eval-llm`)

Subset only (cost): **01-happy**, **03-session-expiry**, **04-ui-rename**, **05-approval-granted**, **06-approval-rejected**. Template → [evals/results/summary-llm.template.md](evals/results/summary-llm.template.md); live table after `make eval-llm` → `evals/results/summary-llm.md` (gitignored).

| Aggregate | Claim |
|-----------|-------|
| Headline | **Subset measured under real Haiku a11y loop** — not a 12/12 CI claim |
| LLM | Anthropic `OPERATOR_MODEL` (default `claude-haiku-5-5`); fails if key missing |
| Repair | Silent RPA repair **off** on this path |

Fill the live aggregate from your latest `summary-llm.md` after a keyed run.

## Architecture

Package: **`ark_operator/`** (SPEC `operator/` renamed — stdlib clash). Event-sourced FSM, irreversible ledger, independent Playwright+API verifier (browser scrape hard-fails submit-class misses), HTMX+SSE UI (Handoff → Work → Proof + Details).

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- [docs/DECISIONS.md](docs/DECISIONS.md)
- [docs/DEMO.md](docs/DEMO.md)
- [docs/SPEC.md](docs/SPEC.md)

## Limitations (honest)

- Invoice **decisions** remain deterministic `PolicyEngine` (LLM owns understand/plan/browser_step/invoice_extract structure).
- DesktopTool **STUB** — no general computer-use / vision fallback.
- Full 12-scenario **real-Haiku** eval every CI run is cost-prohibitive; CI uses FakeLLM (`make eval`). `make eval-llm` covers a keyed Haiku **subset** only — do not market FakeLLM 12/12 as a real-model score.
- On FakeLLM CI, repair after a hard a11y miss may use the RPA shortcut once; the measured first pass is the loop. `make eval-llm` disables that repair.
- Multi-tenant SaaS / embeddings-required memory — explicit non-goals.
