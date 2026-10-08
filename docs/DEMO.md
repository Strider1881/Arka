# Demo (≈90 seconds)

Matches `make demo` / the README story. Portal must be up.

## Prep
```bash
cp .env.example .env   # set PORTAL_OPERATOR_PASSWORD; optional ANTHROPIC_API_KEY
make setup
make portal            # terminal A — http://127.0.0.1:8765
```

## Path A — `make demo` (headless, FakeLLM CI shortcut)

```bash
make demo
# Runs: operator run "…" --auto-approve --only INV-1001,INV-1008,INV-1010
```

What you should see in the CLI report:

1. **INV-1001** — happy submit (Northwind / PO-501).
2. **INV-1008** — under-threshold submit (Umbrella / PO-508).
3. **INV-1010** — processes normally; **SECURITY_FINDING** for the PDF injection (not obeyed).
4. Independent verifier marks completed invoices; false success stays 0.

Browser writes use the **`submit_invoice` shortcut** (real Playwright). With a keyed Anthropic client, CLI/UI use the **Haiku one-action a11y loop** instead — see README dual-path table.

## Path B — UI (full story: approval + proof)

```bash
make ui                # terminal B — http://127.0.0.1:8877
```

1. **Request** — Keep default: “Process this month's pending vendor invoices.” → **Start work**.
2. **Approval** — When INV-1003 appears, the card shows vendor/amount/PO/risk/policy. Click **approve**.
3. **Fault (optional)** — `curl -X POST http://127.0.0.1:8765/admin/faults -H 'content-type: application/json' -d '{"faults":["ui_rename"]}'` then CLI `--only INV-1012` to show label→stable-id recovery + `PLAN_REVISED`.
4. **Proof** — Outcomes + **Verified** panel + evidence thumbnails.
5. **Details** — Tokens/cost, tool calls, plan revisions, full timeline (not the default view).

## CLI one-liner (all invoices, auto-approve)
```bash
make portal &
uv run operator run "Process this month's pending vendor invoices." --auto-approve
```
