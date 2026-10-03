"""Rotating file + console logging."""

from __future__ import annotations

import logging
import logging.handlers
import sys

from .paths import data_dir

_FMT_FILE = "%(asctime)s [%(levelname)-7s] %(name)s: %(message)s"
_FMT_CONS = "%(asctime)s [%(levelname)-7s] %(message)s"


def setup(debug: bool = False) -> logging.Logger:
    logger = logging.getLogger("ultron")
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)
    try:
        fh = logging.handlers.RotatingFileHandler(
            data_dir() / "logs" / "ultron.log",
            maxBytes=1_000_000,
            backupCount=3,
            encoding="utf-8",
        )
        fh.setFormatter(logging.Formatter(_FMT_FILE))
        fh.setLevel(logging.DEBUG)
        logger.addHandler(fh)
    except Exception:  # pragma: no cover - logging must never crash the app
        pass

    sh = logging.StreamHandler(sys.stderr)
    sh.setFormatter(logging.Formatter(_FMT_CONS, datefmt="%H:%M:%S"))
    sh.setLevel(logging.DEBUG if debug else logging.INFO)
    logger.addHandler(sh)
    return logger


def get() -> logging.Logger:
    return logging.getLogger("ultron")
