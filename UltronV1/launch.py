#!/usr/bin/env python3
"""Thin launcher so the app package can be frozen/imported consistently.

Run from the UltronV1 directory:  python launch.py
"""

from app.main import run

if __name__ == "__main__":
    raise SystemExit(run())
