# Prompts

Versioned `.md` prompt files (SPEC §10). Each file starts with `version: N`.

| File | Used by |
|------|---------|
| `understand.md` | `AnthropicClient` / Understander |
| `plan_top.md` | `AnthropicClient` / Planner |

FakeLLM scripts in `build_default_fake_llm()` mirror these for CI without an API key.
