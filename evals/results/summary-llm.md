# Eval results (real LLM) — TODO (no key in this environment)

**Stamped:** not run  
**Measured path:** `a11y_loop + Anthropic (claude-haiku-5-5) — make eval-llm / eval-llm-full`  
**Status:** `ANTHROPIC_API_KEY` was **not** available during submission hardening. **No numbers fabricated.**

## Exact commands to run when a key is present

```bash
# Subset (cost-bounded)
make eval-llm

# Full 12 scenarios × N=3
EVAL_LLM_N=3 make eval-llm-full
# equivalent:
# EVAL_LLM_N=3 uv run python -m evals.runner --llm --full --repeats 3
```

Both paths **fail closed** without a key / invalid `OPERATOR_MODEL` and **never** fall back to FakeLLM.

Template (empty cells): [summary-llm.template.md](summary-llm.template.md)

| scenario | success | notes |
|----------|---------|-------|
| (deferred) | — | Re-run and replace this file; do not treat prior committed tables as current truth |
