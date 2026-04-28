"""
Logging configuration module
Provides unified log management; outputs simultaneously to console and file.
"""

import os
import sys
import logging
from datetime import datetime
from logging.handlers import RotatingFileHandler


def _ensure_utf8_stdout():
    """
    Ensure stdout/stderr use UTF-8 encoding.
    Fixes non-ASCII output garbling on the Windows console.
    """
    if sys.platform == 'win32':
        # On Windows, reconfigure standard output as UTF-8
        if hasattr(sys.stdout, 'reconfigure'):
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        if hasattr(sys.stderr, 'reconfigure'):
            sys.stderr.reconfigure(encoding='utf-8', errors='replace')


# Log directory
LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'logs')


def setup_logger(name: str = 'mirofish', level: int = logging.DEBUG) -> logging.Logger:
    """
    Configure a logger.

    Args:
        name: logger name
        level: log level

    Returns:
        Configured logger
    """
    # Make sure the log directory exists
    os.makedirs(LOG_DIR, exist_ok=True)

    # Create the logger
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Prevent log records from propagating to the root logger to avoid duplicate output
    logger.propagate = False

    # If handlers are already attached, don't add them again
    if logger.handlers:
        return logger

    # Log formatters
    detailed_formatter = logging.Formatter(
        '[%(asctime)s] %(levelname)s [%(name)s.%(funcName)s:%(lineno)d] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    simple_formatter = logging.Formatter(
        '[%(asctime)s] %(levelname)s: %(message)s',
        datefmt='%H:%M:%S'
    )

    # 1. File handler - detailed logs (named by date, with rotation)
    log_filename = datetime.now().strftime('%Y-%m-%d') + '.log'
    file_handler = RotatingFileHandler(
        os.path.join(LOG_DIR, log_filename),
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=5,
        encoding='utf-8'
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(detailed_formatter)

    # 2. Console handler - concise logs (INFO and above)
    # Make sure UTF-8 encoding is used on Windows to avoid garbled non-ASCII output.
    _ensure_utf8_stdout()
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(simple_formatter)

    # Attach handlers
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger


def get_logger(name: str = 'mirofish') -> logging.Logger:
    """
    Get a logger (creating it if it doesn't exist yet).

    Args:
        name: logger name

    Returns:
        Logger instance
    """
    logger = logging.getLogger(name)
    if not logger.handlers:
        return setup_logger(name)
    return logger


# Create the default logger
logger = setup_logger()


# Convenience helpers
def debug(msg, *args, **kwargs):
    logger.debug(msg, *args, **kwargs)

def info(msg, *args, **kwargs):
    logger.info(msg, *args, **kwargs)

def warning(msg, *args, **kwargs):
    logger.warning(msg, *args, **kwargs)

def error(msg, *args, **kwargs):
    logger.error(msg, *args, **kwargs)

def critical(msg, *args, **kwargs):
    logger.critical(msg, *args, **kwargs)
