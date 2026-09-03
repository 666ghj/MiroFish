"""
Logging configuration.

Provides one logger factory for the whole backend, writing to both the console
and a dated file under backend/logs.
"""

import os
import sys
import logging
from datetime import datetime
from logging.handlers import RotatingFileHandler


def _ensure_utf8_stdout():
    """Reconfigure stdout and stderr to UTF-8 on Windows consoles."""
    if sys.platform == 'win32':
        # The Windows console defaults to a legacy code page, which mangles any
        # non-ASCII character the formatters emit.
        if hasattr(sys.stdout, 'reconfigure'):
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        if hasattr(sys.stderr, 'reconfigure'):
            sys.stderr.reconfigure(encoding='utf-8', errors='replace')


# Log directory
LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'logs')


def setup_logger(name: str = 'sosim', level: int = logging.DEBUG) -> logging.Logger:
    """
    Create and configure a logger.

    Args:
        name: Logger name
        level: Logging level

    Returns:
        The configured logger
    """
    # The directory has to exist before the file handler opens its stream.
    os.makedirs(LOG_DIR, exist_ok=True)

    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Records must not propagate to the root logger, or every line is emitted
    # twice once anything else configures logging.
    logger.propagate = False

    # A logger that already has handlers is already configured.
    if logger.handlers:
        return logger

    detailed_formatter = logging.Formatter(
        '[%(asctime)s] %(levelname)s [%(name)s.%(funcName)s:%(lineno)d] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    simple_formatter = logging.Formatter(
        '[%(asctime)s] %(levelname)s: %(message)s',
        datefmt='%H:%M:%S'
    )

    # 1. File handler - full detail, one file per day, rotated.
    log_filename = datetime.now().strftime('%Y-%m-%d') + '.log'
    file_handler = RotatingFileHandler(
        os.path.join(LOG_DIR, log_filename),
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=5,
        encoding='utf-8'
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(detailed_formatter)

    # 2. Console handler - a short line, INFO and above.
    _ensure_utf8_stdout()
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(simple_formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger


def get_logger(name: str = 'sosim') -> logging.Logger:
    """
    Return a logger, configuring it on first use.

    Args:
        name: Logger name

    Returns:
        The logger instance
    """
    logger = logging.getLogger(name)
    if not logger.handlers:
        return setup_logger(name)
    return logger


# The default logger, used by the module-level convenience functions below.
logger = setup_logger()


# Convenience wrappers
def debug(msg: str, *args, **kwargs) -> None:
    logger.debug(msg, *args, **kwargs)

def info(msg: str, *args, **kwargs) -> None:
    logger.info(msg, *args, **kwargs)

def warning(msg: str, *args, **kwargs) -> None:
    logger.warning(msg, *args, **kwargs)

def error(msg: str, *args, **kwargs) -> None:
    logger.error(msg, *args, **kwargs)

def critical(msg: str, *args, **kwargs) -> None:
    logger.critical(msg, *args, **kwargs)
