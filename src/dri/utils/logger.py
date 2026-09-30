"""Structured logging setup for DRI agent."""

import json
import logging
import sys
from typing import Any, Optional

from pythonjsonlogger import jsonlogger


def setup_logging(
    level: str = "INFO",
    json_format: bool = False,
    log_file: Optional[str] = None,
) -> logging.Logger:
    """
    Configure structured logging for the DRI agent.

    Args:
        level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        json_format: Use JSON format for structured logging
        log_file: Optional file path for log output

    Returns:
        Configured logger instance
    """
    logger = logging.getLogger("dri")
    logger.setLevel(getattr(logging, level.upper()))

    # Clear existing handlers
    logger.handlers = []

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(getattr(logging, level.upper()))

    if json_format:
        # Use %(message)s and %(levelname)s — both are real LogRecord fields.
        # pythonjsonlogger does NOT support %(timestamp)s or %(level)s.
        formatter = jsonlogger.JsonFormatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s"
        )
        console_handler.setFormatter(formatter)
    else:
        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        console_handler.setFormatter(formatter)

    logger.addHandler(console_handler)

    # File handler (optional)
    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(getattr(logging, level.upper()))

        if json_format:
            file_formatter = jsonlogger.JsonFormatter(
                "%(asctime)s %(levelname)s %(name)s %(message)s"
            )
            file_handler.setFormatter(file_formatter)
        else:
            file_handler.setFormatter(formatter)

        logger.addHandler(file_handler)

    return logger


class ContextLogger:
    """Logger that accepts arbitrary keyword context without raising TypeError.

    Standard ``logging.Logger`` raises ``TypeError`` when unknown keyword
    arguments are passed (e.g. ``logger.info("msg", container_id="x")``).
    This wrapper intercepts those kwargs, merges them with a persistent
    context dict, and formats them into the log message so the output is
    still human-readable without requiring a JSON formatter.
    """

    def __init__(self, name: str, context: Optional[dict] = None):
        self.logger = logging.getLogger(name)
        self.context = context or {}

    def _format(self, msg: Any, kwargs: dict) -> str:
        """Merge context + kwargs into the message string."""
        merged = {**self.context, **kwargs}
        if merged:
            extras = " ".join(f"{k}={v!r}" for k, v in merged.items())
            return f"{msg} [{extras}]"
        return str(msg)

    def debug(self, msg: Any, **kwargs: Any) -> None:
        self.logger.debug(self._format(msg, kwargs))

    def info(self, msg: Any, **kwargs: Any) -> None:
        self.logger.info(self._format(msg, kwargs))

    def warning(self, msg: Any, **kwargs: Any) -> None:
        self.logger.warning(self._format(msg, kwargs))

    def error(self, msg: Any, **kwargs: Any) -> None:
        self.logger.error(self._format(msg, kwargs))

    def critical(self, msg: Any, **kwargs: Any) -> None:
        self.logger.critical(self._format(msg, kwargs))


def get_logger(name: str) -> "ContextLogger":
    """Get a ContextLogger instance by name.

    Returns a :class:`ContextLogger` (not a bare ``logging.Logger``) so that
    callers can safely pass keyword arguments such as
    ``logger.info("msg", container_id="x", success=True)`` without raising
    ``TypeError``.
    """
    return ContextLogger(f"dri.{name}")
