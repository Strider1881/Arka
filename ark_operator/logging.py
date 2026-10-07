"""Structured logging via structlog — secrets redacted from event dicts."""

from __future__ import annotations

import logging
import os
from collections.abc import MutableMapping
from typing import Any

import structlog

_SECRET_KEYS = frozenset(
    {"password", "api_key", "token", "secret", "authorization", "anthropic_api_key"}
)


def _scrub(value: Any, secrets: list[str]) -> Any:
    if isinstance(value, dict):
        return {
            k: ("***REDACTED***" if k.lower() in _SECRET_KEYS else _scrub(v, secrets))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_scrub(v, secrets) for v in value]
    if isinstance(value, str):
        out = value
        for secret in secrets:
            if secret and secret in out:
                out = out.replace(secret, "***REDACTED***")
        return out
    return value


def _redact_processor(
    logger: Any, method_name: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    del logger, method_name
    secrets = [
        os.environ.get("PORTAL_OPERATOR_PASSWORD", ""),
        os.environ.get("PORTAL_MANAGER_PASSWORD", ""),
        os.environ.get("ANTHROPIC_API_KEY", ""),
    ]
    scrubbed = _scrub(dict(event_dict), secrets)
    assert isinstance(scrubbed, dict)
    event_dict.clear()
    event_dict.update(scrubbed)
    return event_dict


def configure_logging(level: str = "INFO") -> None:
    """Configure structlog + stdlib logging for the process."""
    logging.basicConfig(format="%(message)s", level=getattr(logging, level.upper(), logging.INFO))
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            _redact_processor,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> Any:
    """Return a bound structlog logger."""
    return structlog.get_logger(name)
