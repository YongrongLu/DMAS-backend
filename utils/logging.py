"""Structured logging

Provides:
- setup_logging:    configure structlog once at process start
- get_logger:       a logger bound to a module name

Key constraints:
- logs go to stderr so they never mix with skill JSON on stdout
"""

import logging
import sys

import structlog


def setup_logging(level: str = "INFO") -> None:
    """Configure colored console logging filtered by level."""
    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="%H:%M:%S"),
            structlog.dev.ConsoleRenderer(colors=True),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, level.upper(), logging.INFO)),
        logger_factory=structlog.PrintLoggerFactory(sys.stderr),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str = __name__):
    """Return a structlog logger bound to a name."""
    return structlog.get_logger(name)
