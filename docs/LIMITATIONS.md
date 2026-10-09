# Limitations (honest)

Operator is a **narrow invoice-processing demo**, not a generic multi-workflow runtime.

## What is real

- Invoice decisions: deterministic `PolicyEngine` (params from `company_world/knowledge/*.md`; `rules.yaml` is permissions-only).
- Portal writes: Playwright Chromium via the **a11y observe→act loop** (default).
- Independent verifier: fresh portal API session + isolated browser scrape (agent never grades itself).
- Approvals: plain HTML form POST (works with JS disabled); over-threshold INV-1003 pauses before irreversible submit.
- After operator clearance + portal `PENDING_APPROVAL`, proof outcome is **Submitted, awaiting manager approval** (`SUBMITTED_AWAITING_MANAGER`) — distinct from manager-queue `APPROVED`.
- Fault recovery: session expiry / ui_rename / flaky_500 on the FakeLLM a11y path.
- CLI and UI share `OPERATOR_DB_PATH` (one EventStore).

## What is not claimed

- **FakeLLM 12/12 is CI harness correctness**, not a real-model score. Do not market it as Haiku performance.
- **`make eval-llm` / `eval-llm-full`** require `ANTHROPIC_API_KEY` and a docs-allowlisted `OPERATOR_MODEL` (`claude-haiku-5-5` default). They **never** fall back to FakeLLM. If the key is missing, those targets exit 2 with exact commands — no fabricated numbers.
- Top-level LLM plans are structural/logging; EXECUTE follows the invoice procedure + policy decisions.
- DesktopTool remains **STUB**.
- RPA `submit_invoice` shortcut is optional (`make eval-rpa`) and **off** on measured a11y paths.
- Real-Haiku fail→replan under always-on `ui_rename` is not claimed.
- Second declarative procedure / multi-workflow runtime (Phase E) is **deferred** unless explicitly landed.

## Product name

UI/docs product name: **Operator**. Python package remains `ark_operator/` (stdlib `operator` clash) — see DECISIONS.md.
