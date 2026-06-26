"""Structured logger configuration."""
from __future__ import annotations

import logging
import sys
from typing import Any

from app.config import get_settings


def configure_logging() -> None:
    """Configure root logger once."""
    settings = get_settings()
    level = getattr(logging, settings.log_level.upper(), logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
    )

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)


def get_logger(name: str) -> logging.Logger:
    """Return a named logger."""
    return logging.getLogger(name)


def log_event(logger: logging.Logger, event: str, **fields: Any) -> None:
    """Emit a structured log event with key=value pairs."""
    if fields:
        rendered = " ".join(f"{k}={v}" for k, v in fields.items())
        logger.info("%s | %s", event, rendered)
    else:
        logger.info("%s", event)