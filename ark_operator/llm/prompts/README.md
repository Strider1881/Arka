# Prompts

Versioned `.md` prompt files (SPEC §10). Each file starts with `version: N`.

| File | Used by |
|------|---------|
| `understand.md` | `AnthropicClient` / Understander |
| `plan_top.md` | `AnthropicClient` / Planner |
| `browser_step.md` | `AnthropicClient` / `BrowserLoop` (one a11y action) |

FakeLLM scripts in `build_default_fake_llm()` mirror understand/plan for CI without an API key.
`scripted_browser_step` in `runtime/browser_loop.py` drives the a11y loop when
`PipelineConfig.use_browser_loop=True` under FakeLLM (CI fast path otherwise uses
`submit_invoice`).
