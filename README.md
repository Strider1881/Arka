# Operator

An autonomous AI employee that turns a short company request into **completed** work,
proves it with independent verification, and only interrupts a human when policy or
ambiguity requires it.

> **Pitch:** An employee that finishes the job, proves it, and only interrupts you when it truly matters.

**Product name:** Operator. Python package: `ark_operator/` (stdlib `operator` clash — see [docs/DECISIONS.md](docs/DECISIONS.md)).

## The 90-second story

1. Type: `Process this month's pending vendor invoices.`
2. Operator understands the goal, loads AcmeCorp policy (KB markdown is SSoT for thresholds), extracts inbox PDFs, and works the procurement portal via the **a11y observe→act browser loop**.
3. INV-1003 (over $5k) pauses for one approval card (summary + policy + risk). Approve → resume → portal `PENDING_APPROVAL`. Proof: **Submitted, awaiting manager approval**.
4. Injected faults (session expiry / renamed Submit button) recover; INV-1010 injection is recorded, not obeyed.
5. Proof screen: per-invoice outcomes + independent **Verified** panel (API + hard browser scrape). Details shows tokens/cost/timeline.

Reproduce headlessly: `make demo` (spawns its own portal — fault + approval pause + verifier sabotage + proof). Interactive UI: `make portal` + `make ui`. Full script: [docs/DEMO.md](docs/DEMO.md).

## Measured paths (honest dual track)

Two eval targets — do not conflate them:

| Target | LLM | Browser path | What it proves |
|--------|-----|--------------|----------------|
| **`make eval`** | FakeLLM (scripted) | a11y loop (`scripted_browser_step`) | **Deterministic CI / harness correctness** — policy + portal + verifier + recovery wiring (12/12). Not a real-model score. |
| **`make eval-llm`** | Real Anthropic Haiku (`ANTHROPIC_API_KEY`, `OPERATOR_MODEL=claude-haiku-5-5`) | a11y loop (model chooses actions) | Same subset under a real model; **no FakeLLM fallback**; RPA repair disabled |
| **`make eval-llm-full`** | Real Haiku | a11y loop | All 12 scenarios × `EVAL_LLM_N` (default 3). Costly; stamps `summary-llm.md`. |

| Path | When | Browser writes |
|------|------|----------------|
| **a11y loop (default)** | `make eval` / `make eval-llm`, CLI/UI default | Observe compact a11y tree → LLM picks **one** action → tool → repeat until postcondition |
| **RPA shortcut (optional)** | `make eval-rpa` / `--no-browser-loop` | High-level `submit_invoice` (still real Playwright) — micro-benchmark only; **not** the measured a11y path |

Policy decisions and verification are **never** FakeLLM. DesktopTool remains **STUB**.

**Runtime:** `InvoicePipeline` owns phases end-to-end (FSM). `Orchestrator` allocates `run_id` only. Top-level LLM plans are structural/logging; EXECUTE follows the invoice procedure. Per-invoice sub-plans mirror `PolicyEngine` decisions (browser / ask_human dispatch), they do not discover policy.

## Quickstart

```bash
cp .env.example .env
# Set PORTAL_OPERATOR_PASSWORD (and optional PORTAL_ADMIN_TOKEN, ANTHROPIC_API_KEY)
make setup                             # hermetic inbox PDFs — clean git after
make lint && make test && make eval    # FakeLLM CI harness (deterministic)
make eval-llm                          # real Haiku subset (needs ANTHROPIC_API_KEY)
make eval-llm-full                     # full 12×N (needs key; default N=3)
make demo                              # self-contained 90s story (own portal)
make portal                            # terminal A — http://127.0.0.1:8765
make ui                                # terminal B — http://127.0.0.1:8877
```

Never commit `.env`. Portal `/admin/faults` requires auth (session or `PORTAL_ADMIN_TOKEN`). Passwords are PBKDF2-hashed. `make demo` does not need a pre-started portal. CLI and UI share **`OPERATOR_DB_PATH`** (`data/operator.db`). `make eval-llm` / `eval-llm-full` exit nonzero if the key is missing — they never silently use FakeLLM.

### CLI

```bash
uv run operator run "Process this month's pending vendor invoices."
uv run operator approve <run_id> --step INV-1003          # SPEC shape
uv run operator status <run_id>
uv run operator replay <run_id>
uv run operator eval                                      # FakeLLM a11y harness
uv run operator eval --llm                                # real Haiku subset
```

## Eval results

### FakeLLM CI harness (`make eval`)

Latest run → [evals/results/summary.md](evals/results/summary.md). This is **deterministic CI / harness correctness**, not Haiku performance.

| Aggregate | Result |
|-----------|--------|
| task_success | **12/12** |
| false_success_rate | **0.00** |
| unsafe_actions | **0** |
| LLM | FakeLLM (scripted a11y steps) |

### Real Haiku (`make eval-llm` / `eval-llm-full`)

Requires `ANTHROPIC_API_KEY`. Model preflight allowlists docs-confirmed **`claude-haiku-5-5`**. See [evals/results/summary-llm.md](evals/results/summary-llm.md) (TODO stamped when no key) and [summary-llm.template.md](evals/results/summary-llm.template.md).

**Do not fabricate or rubber-stamp Haiku numbers without a keyed re-run.**

## Architecture

Package: **`ark_operator/`**. Event-sourced FSM, irreversible ledger, independent Playwright+API verifier, HTMX+SSE UI (Handoff → Work → Proof + Details). Policy params from knowledge markdown.

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- [docs/DECISIONS.md](docs/DECISIONS.md)
- [docs/DEMO.md](docs/DEMO.md)
- [docs/SPEC.md](docs/SPEC.md)
- [docs/LIMITATIONS.md](docs/LIMITATIONS.md)
- [docs/AUDIT.md](docs/AUDIT.md) — historical engineering audit; reconcile against code + LIMITATIONS (invoice control plane is intentional)

## Limitations

See [docs/LIMITATIONS.md](docs/LIMITATIONS.md) for the full honest list (FakeLLM ≠ real model, DesktopTool STUB, Phase E deferred, etc.).
