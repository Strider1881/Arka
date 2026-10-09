# Demo (≈90 seconds)

Matches `make demo` / the README story. Portal may already be up, or the demo spawns one.

## Prep
```bash
cp .env.example .env   # set PORTAL_OPERATOR_PASSWORD; optional ANTHROPIC_API_KEY
make setup             # hermetic inbox PDFs — git status stays clean
make portal            # terminal A — http://127.0.0.1:8765 (optional if demo spawns)
export PORTAL_ADMIN_TOKEN=demo-admin-token
```

## Path A — `make demo` (headless 90s story)

```bash
make demo
```

Spawns a **dedicated** portal with known demo credentials (self-contained).  
Set `DEMO_USE_EXISTING_PORTAL=1` only if you intentionally want `PORTAL_BASE_URL`.

Automated narrative:

1. **Fault + recovery** — enable `ui_rename`, process INV-1012 via a11y loop; expect `RECOVERY_ATTEMPTED` + proof.
2. **Approval pause** — INV-1003 with `auto_approve=None`; seeded decide; resume submit → portal `PENDING_APPROVAL`.
   Proof outcome: **Submitted, awaiting manager approval** (`SUBMITTED_AWAITING_MANAGER`) with `verified=yes` when the independent verifier passes.
3. **Verifier catch** — sabotage invoice with no portal row → verification fails (false_success stays 0).
4. **Proof** — INV-1001 submit + independent verify (API + browser scrape).

**B1 note:** Approval threshold ($5,000) and tolerance (2%) load from `company_world/knowledge/approval_policy.md` and `tolerance_policy.md` — not from `rules.yaml`. Changing the KB threshold changes INV-1003’s decision (see unit test).

Browser writes use the **a11y loop** by default (`scripted_browser_step` under FakeLLM CI harness).

## Path B — UI (interactive)

```bash
make ui                # terminal B — http://127.0.0.1:8877
```

CLI and UI share `OPERATOR_DB_PATH` (`data/operator.db` by default) — `operator status` / `operator approve` work on UI-started runs.

1. **Request** — Keep default → **Start work**.
2. **Approval** — INV-1003 card (above the fold) → **approve** (plain form POST; works with JS off).
3. **Fault** — `curl -X POST http://127.0.0.1:8765/admin/faults -H 'x-portal-admin-token: demo-admin-token' -H 'content-type: application/json' -d '{"faults":["ui_rename"]}'` then CLI `--only INV-1012`.
4. **Proof** — Outcomes + **Verified** panel + evidence thumbnails. INV-1003 shows “Submitted, awaiting manager approval”.
5. **Details** — Tokens/cost, tool calls, plan revisions, full timeline.

## CLI
```bash
uv run operator run "Process this month's pending vendor invoices." --auto-approve
uv run operator approve <run_id> --step INV-1003
uv run operator status <run_id>
```
