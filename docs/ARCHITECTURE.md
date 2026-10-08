# Architecture

## One-sentence design
An event-sourced Operator turns a company request into completed portal work, proves outcomes with an independent verifier, and interrupts humans only for policy/ambiguity.

## Runtime loop

```mermaid
stateDiagram-v2
    [*] --> INTAKE
    INTAKE --> UNDERSTAND
    UNDERSTAND --> PLAN
    UNDERSTAND --> CLARIFY: blocked question
    CLARIFY --> PLAN
    CLARIFY --> AWAIT_APPROVAL: ask human
    AWAIT_APPROVAL --> PLAN: clarify decided
    PLAN --> EXECUTE
    EXECUTE --> AWAIT_APPROVAL: policy requires human
    AWAIT_APPROVAL --> EXECUTE: decided
    EXECUTE --> VERIFY
    VERIFY --> REPAIR: mismatch
    REPAIR --> EXECUTE
    VERIFY --> REPORT: ok or repair exhausted
    REPORT --> COMPLETE
    EXECUTE --> FAILED
    EXECUTE --> ESCALATED
```

**Single control plane:** `InvoicePipeline` owns all phases via `StateMachine` / FSM. `Orchestrator.start()` only allocates `run_id`. Per-invoice sub-plans drive `_act_on_invoice` (browser / ask_human steps).

## Event sourcing

```mermaid
flowchart LR
  Tools --> Events[(SQLite events append-only)]
  Events --> Fold[Fold working state]
  Fold --> Pipeline[InvoicePipeline]
  Pipeline --> Tools
  Events --> Replay[Replay timeline]
  Events --> Verifier
  PortalAPI[portal_api read-only] --> Verifier
  BrowserScrape[isolated Playwright scrape] --> Verifier
```

## Trust boundaries
- PDF/web text wrapped as `<<<UNTRUSTED_DATA>>>` — never instructions
- Passwords via secrets provider; portal stores PBKDF2 hashes; redacted from logs/events
- Verifier uses a **fresh** Playwright context + portal_api session (agent never grades itself)
- Submit-class browser scrape is a **hard** criterion (miss fails the run)
- Irreversible submits require policy clearance + idempotency keys
- `/admin/faults` requires auth

## Browser execute→observe→adapt (SPEC §6.5–6.7)

```mermaid
flowchart LR
  Observe[a11y observe + refs] --> LLM[LLM browser_step]
  LLM --> Act[one action: login/goto/click/fill/select]
  Act --> Observe
  Observe --> Done{postcondition / budget / stall}
```

### Measured vs optional path

| Path | Trigger | Writes |
|------|---------|--------|
| **a11y loop (default)** | `make eval`, `use_browser_loop=True` | One LLM-chosen action at a time (`scripted_browser_step` under FakeLLM) |
| RPA shortcut (optional) | `make eval-rpa` / `--no-browser-loop` | High-level `submit_invoice` (still real Playwright) |

Clearance + `IrreversibleLedger` + independent verifier wrap **both** paths. Policy/verify never go through FakeLLM.

## Package map
- `ark_operator/runtime` — pipeline (phases), browser_loop, recovery, budgets, stall, plan_revision
- `ark_operator/tools` — browser, pdf_extract (LLM+confidence), files, knowledge, portal_api, ask_human
- `ark_operator/policy` — rules.yaml + decision engine
- `ark_operator/verify` — independent checks + evidence
- `ark_operator/memory` — knowledge FTS + event-conditioned episodic lessons
- `company_world` — deterministic AcmeCorp Procure world
