"""Structured logging via structlog — secrets via central redactor."""

from __future__ import annotations

import logging
from collections.abc import MutableMapping
from typing import Any

import structlog

from ark_operator.security.redact import redact_payload


def _redact_processor(
    logger: Any, method_name: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    del logger, method_name
    scrubbed = redact_payload(dict(event_dict))
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
