"""Filesystem path resolution for frozen (PyInstaller) and dev runs."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def bundle_dir() -> Path:
    """Directory of bundled read-only resources (PyInstaller _MEIPASS when frozen)."""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parent


def install_dir() -> Path:
    """Directory the executable (or the app package) lives in."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def data_dir() -> Path:
    """Per-user writable data directory (config, logs, models, temp files)."""
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    d = base / "Ultron"
    for sub in ("logs", "models", "tmp"):
        (d / sub).mkdir(parents=True, exist_ok=True)
    return d


def resource(rel: str) -> Path:
    """Locate a resource by relative path.

    Search order: bundled (frozen) location -> app package dir -> user data dir.
    """
    rel = rel.replace("\\", "/").lstrip("/")
    candidates = [
        bundle_dir() / rel,
        install_dir() / rel,
        data_dir() / rel,
    ]
    for c in candidates:
        if c.exists():
            return c
    return candidates[0]
