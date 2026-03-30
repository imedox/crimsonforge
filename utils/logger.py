"""Structured logging system with file and console output.

Provides a configured logger for the entire application with
configurable log levels, file output, and formatted console output.
"""

import logging
import sys
from pathlib import Path
from typing import Optional


_logger_instance: Optional[logging.Logger] = None


def setup_logger(
    log_level: str = "INFO",
    log_file: str = "",
    debug_mode: bool = False,
    name: str = "crimsonforge"
) -> logging.Logger:
    """Initialize and configure the application logger.

    Args:
        log_level: Logging level string (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: Path to log file. Empty string means no file logging.
        debug_mode: If True, forces DEBUG level and adds detailed formatting.
        name: Logger name.

    Returns:
        Configured logger instance.
    """
    global _logger_instance

    logger = logging.getLogger(name)
    logger.handlers.clear()
    logger.propagate = False

    level = logging.DEBUG if debug_mode else getattr(logging, log_level.upper(), logging.INFO)
    logger.setLevel(level)

    if debug_mode:
        console_fmt = logging.Formatter(
            "%(asctime)s [%(levelname)-8s] %(name)s:%(funcName)s:%(lineno)d - %(message)s",
            datefmt="%H:%M:%S"
        )
    else:
        console_fmt = logging.Formatter(
            "%(asctime)s [%(levelname)-8s] %(message)s",
            datefmt="%H:%M:%S"
        )

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(console_fmt)
    logger.addHandler(console_handler)

    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_fmt = logging.Formatter(
            "%(asctime)s [%(levelname)-8s] %(name)s:%(funcName)s:%(lineno)d - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        file_handler = logging.FileHandler(str(log_path), encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(file_fmt)
        logger.addHandler(file_handler)

    _logger_instance = logger
    return logger


def get_logger(module_name: str = "") -> logging.Logger:
    """Get the application logger, optionally with a child name.

    Args:
        module_name: Sub-module name (e.g., 'core.crypto'). If empty, returns root logger.

    Returns:
        Logger instance.
    """
    global _logger_instance
    if _logger_instance is None:
        _logger_instance = setup_logger()

    if module_name:
        return _logger_instance.getChild(module_name)
    return _logger_instance
