# Eval results (real LLM)

**Measured path:** `a11y_loop + Anthropic (claude-haiku-5-5) — make eval-llm`

No FakeLLM. RPA repair after a11y miss is **disabled** on this path.

Run locally (requires `ANTHROPIC_API_KEY` in `.env`):

```bash
make eval-llm
```

Live output is written to `evals/results/summary-llm.md` (gitignored). Fill the table after a successful run, or commit that file only when it contains no secrets.

| Scenario | task_success | decisions | false_success | unsafe | approvals_ok | recoveries | steps | cost_usd | wall_s |
|----------|--------------|-----------|---------------|--------|--------------|------------|-------|----------|--------|
| 01-happy | — | — | — | — | — | — | — | — | — |
| 03-session-expiry | — | — | — | — | — | — | — | — | — |
| 04-ui-rename | — | — | — | — | — | — | — | — | — |
| 05-approval-granted | — | — | — | — | — | — | — | — | — |
| 06-approval-rejected | — | — | — | — | — | — | — | — | — |

Aggregate task_success: **—**
Aggregate cost_usd sum: **—**
