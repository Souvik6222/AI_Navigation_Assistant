# ============================================================
# utils/logger.py — Structured logging for the navigation assistant
# ============================================================

import logging
import sys


# ANSI color codes for console output
_COLORS = {
    "DEBUG": "\033[36m",     # Cyan
    "INFO": "\033[32m",      # Green
    "WARNING": "\033[33m",   # Yellow
    "ERROR": "\033[31m",     # Red
    "CRITICAL": "\033[41m",  # Red background
    "RESET": "\033[0m",
}


class _ColoredFormatter(logging.Formatter):
    """Formatter that adds ANSI colors to log level names."""

    def format(self, record):
        level = record.levelname
        color = _COLORS.get(level, "")
        reset = _COLORS["RESET"]
        record.levelname = f"{color}{level}{reset}"
        return super().format(record)


def get_logger(name: str, level: str = "INFO") -> logging.Logger:
    """
    Create a structured logger with colored console output.

    Args:
        name: Module name (e.g., 'detector', 'voice').
        level: Log level string — DEBUG, INFO, WARNING, ERROR.

    Returns:
        Configured logging.Logger instance.
    """
    logger = logging.getLogger(f"nav.{name}")

    # Prevent duplicate handlers if called multiple times
    if logger.handlers:
        return logger

    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Console handler with colors
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG)
    formatter = _ColoredFormatter(
        fmt="[%(asctime)s] %(levelname)s [%(name)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # Prevent propagation to root logger
    logger.propagate = False

    return logger


def setup_file_logging(logger: logging.Logger, filepath: str):
    """
    Add a file handler to an existing logger.

    Args:
        logger: Logger instance to add file handler to.
        filepath: Path to log file.
    """
    file_handler = logging.FileHandler(filepath, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter(
        fmt="[%(asctime)s] %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
