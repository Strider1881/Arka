"""Fail-closed OPERATOR_MODEL preflight for real-LLM paths (eval-llm / UI).

Valid IDs are sourced from Anthropic docs (Haiku 5.5 API id ``claude-haiku-5-5``,
confirmed 2026-10). When ``ANTHROPIC_API_KEY`` is set we optionally probe
``client.models.retrieve``; network failure with an allowlisted id is a warning
only — unknown ids always fail closed. Never falls back to FakeLLM.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

# Claude API IDs documented as active for this take-home default path.
# Do not invent IDs — extend only from https://docs.anthropic.com / platform docs.
ALLOWED_OPERATOR_MODELS = frozenset(
    {
        "claude-haiku-5-5",
        "claude-haiku-4-5",
        "claude-haiku-4-5-20251001",
    }
)


@dataclass(frozen=True)
class ModelPreflightResult:
    ok: bool
    model: str
    detail: str


def preflight_operator_model(
    model: str,
    *,
    api_key: str | None = None,
    probe_api: bool = True,
) -> ModelPreflightResult:
    """Validate OPERATOR_MODEL before starting a real-LLM run."""
    name = (model or "").strip()
    if not name:
        return ModelPreflightResult(False, name, "OPERATOR_MODEL is empty")
    if name not in ALLOWED_OPERATOR_MODELS:
        return ModelPreflightResult(
            False,
            name,
            (
                f"OPERATOR_MODEL={name!r} is not in the allowlist "
                f"{sorted(ALLOWED_OPERATOR_MODELS)}. "
                "Update only from Anthropic docs — do not guess."
            ),
        )
    key = (api_key if api_key is not None else os.environ.get("ANTHROPIC_API_KEY", "")).strip()
    if not probe_api or not key:
        return ModelPreflightResult(True, name, "allowlist ok (API probe skipped)")
    try:
        import anthropic

        client = anthropic.Anthropic(api_key=key)
        # models.retrieve raises on unknown ids when the SDK/API supports it.
        retrieve = getattr(getattr(client, "models", None), "retrieve", None)
        if callable(retrieve):
            retrieve(name)
            return ModelPreflightResult(True, name, "allowlist + API retrieve ok")
    except Exception as exc:  # noqa: BLE001 — fail closed only on NotFound-like
        msg = str(exc).lower()
        if "not_found" in msg or "404" in msg or "not found" in msg:
            return ModelPreflightResult(False, name, f"API rejected model: {exc}")
        # Transport / auth issues: allowlisted id still permitted (eval can fail later).
        return ModelPreflightResult(
            True, name, f"allowlist ok (API probe inconclusive: {type(exc).__name__})"
        )
    return ModelPreflightResult(True, name, "allowlist ok")


def require_valid_operator_model(model: str, *, api_key: str | None = None) -> str:
    """Raise RuntimeError when the model is not usable for a real-LLM path."""
    result = preflight_operator_model(model, api_key=api_key, probe_api=True)
    if not result.ok:
        raise RuntimeError(result.detail)
    return result.model
