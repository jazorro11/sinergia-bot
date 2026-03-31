"""Centralized logging: stdout, format and level from LOG_LEVEL."""

import logging
import os
import sys


def _parse_log_level() -> int:
    raw = os.environ.get("LOG_LEVEL", "INFO")
    level = getattr(logging, raw.upper(), None)
    if isinstance(level, int):
        return level
    return logging.INFO


def _configure_logging() -> None:
    logging.basicConfig(
        level=_parse_log_level(),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
        force=True,
    )


_configure_logging()


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
