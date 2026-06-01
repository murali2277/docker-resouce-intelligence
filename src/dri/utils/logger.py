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
        formatter = jsonlogger.JsonFormatter(
            "%(timestamp)s %(level)s %(name)s %(message)s"
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
                "%(timestamp)s %(level)s %(name)s %(message)s"
            )
            file_handler.setFormatter(file_formatter)
        else:
            file_handler.setFormatter(formatter)

        logger.addHandler(file_handler)

    return logger


class ContextLogger:
    """Logger with contextual information."""

    def __init__(self, name: str, context: Optional[dict] = None):
        self.logger = logging.getLogger(name)
        self.context = context or {}

    def _add_context(self, data: Any) -> Any:
        """Add context to log data."""
        if isinstance(data, dict):
            return {**self.context, **data}
        return {**self.context, "message": data}

    def debug(self, msg: Any, **kwargs: Any) -> None:
        self.logger.debug(self._add_context(kwargs or msg))

    def info(self, msg: Any, **kwargs: Any) -> None:
        self.logger.info(self._add_context(kwargs or msg))

    def warning(self, msg: Any, **kwargs: Any) -> None:
        self.logger.warning(self._add_context(kwargs or msg))

    def error(self, msg: Any, **kwargs: Any) -> None:
        self.logger.error(self._add_context(kwargs or msg))

    def critical(self, msg: Any, **kwargs: Any) -> None:
        self.logger.critical(self._add_context(kwargs or msg))


def get_logger(name: str) -> logging.Logger:
    """Get a logger instance by name."""
    return logging.getLogger(f"dri.{name}")
