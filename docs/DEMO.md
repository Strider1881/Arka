# Demo (≈90 seconds)

## Prep
```bash
cp .env.example .env   # set PORTAL_OPERATOR_PASSWORD
make setup
make portal            # terminal A — http://127.0.0.1:8765
make ui                # terminal B — http://127.0.0.1:8877
```

## Script
1. **Request** — Open Operator UI. Keep the default: “Process this month's pending vendor invoices.” Click **Start work**.
2. **Fault (optional)** — In another shell: `curl -X POST http://127.0.0.1:8765/admin/faults -H 'content-type: application/json' -d '{"faults":["ui_rename"]}'`. Re-run a single invoice via CLI to show stable element ids still work.
3. **Approval** — When INV-1003 (over $5k) appears, click **approve** on the interruption card.
4. **Proof** — Land on the proof screen: per-invoice outcomes + **Verified** panel. Open **Details** for the event timeline.
5. **Verifier catch** — Note flagged/refused invoices are not claimed as completed; security finding listed for INV-1010.

## CLI alternative
```bash
make portal &
uv run operator run "Process this month's pending vendor invoices." --auto-approve
```

## make demo
`make demo` regenerates PDFs and runs a headless CLI subset (INV-1001, INV-1008, INV-1010) against a running portal.
