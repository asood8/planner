"""Logging for both entry points: a rotating data/planner.log, plus the console.

The log file is what's left after an unattended run (like the scheduled morning plan), so it gets
tracebacks; the console gets one line per problem. Never log calendar or email content, only what
happened: counts, statuses, and errors.
"""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from core.local_store import data_path

LOG_FILE = "planner.log"
MAX_BYTES = 1_000_000
BACKUP_COUNT = 3
FILE_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
# Chatty libraries: request lines from the dev server, and a harmless discovery-cache warning.
QUIET_LOGGERS = {"werkzeug": logging.WARNING, "googleapiclient.discovery_cache": logging.ERROR}


class _ConsoleFormatter(logging.Formatter):
    """Plain messages for info; "Warning: ..." / "Error: ..." otherwise; tracebacks stay in the file."""

    def format(self, record: logging.LogRecord) -> str:
        message = record.getMessage()
        return message if record.levelno <= logging.INFO else f"{record.levelname.title()}: {message}"


def _planner_handlers(root: logging.Logger) -> list[logging.Handler]:
    return [handler for handler in root.handlers if getattr(handler, "planner_handler", False)]


def teardown_logging() -> None:
    """Remove the handlers setup_logging() added (used by tests, and before setting up again)."""
    root = logging.getLogger()
    for handler in _planner_handlers(root):
        root.removeHandler(handler)
        handler.close()


def setup_logging(console: bool = True) -> None:
    teardown_logging()
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    path = data_path(LOG_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(path, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(FILE_FORMAT))
    handlers: list[logging.Handler] = [file_handler]

    if console:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(_ConsoleFormatter())
        handlers.append(console_handler)

    for handler in handlers:
        handler.planner_handler = True
        root.addHandler(handler)
    for name, level in QUIET_LOGGERS.items():
        logging.getLogger(name).setLevel(level)


def log_failure(logger: logging.Logger, message: str, exc: BaseException) -> None:
    """A one-line warning with the reason; the traceback goes to the log file only."""
    logger.warning("%s: %s", message, exc)
    logger.debug("%s (details)", message, exc_info=exc)
