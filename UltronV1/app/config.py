"""Configuration persisted to %APPDATA%/Ultron/config.json."""

from __future__ import annotations

import copy
import json
from typing import Any

from .paths import data_dir

DEFAULTS: dict[str, Any] = {
    "wake_word": "ultron",
    "hotkey": "ctrl+alt+u",
    "llm": {
        "base_url": "http://127.0.0.1:11434",
        "model": "llama3.2:3b",
        "temperature": 0.6,
        "max_history": 12,
    },
    "voice": {
        # SAPI voice name substring; empty = auto-pick a deep male voice.
        "sapi_voice": "",
        # SAPI XML pitch (-50..50). Negative = deeper.
        "sapi_pitch": -12,
        # SAPI rate (-10..10). Slightly slow feels more menacing.
        "sapi_rate": -1,
        "sapi_volume": 100,
        # Post-processing intensity 0.0 .. 1.5 (chorus, ring-mod, reverb...).
        "fx_intensity": 1.0,
        # Extra pitch drop applied in the FX chain, in semitones (0..7).
        "fx_pitch_semitones": 2.5,
        "volume": 0.9,
    },
    "stt": {
        "model_dir": "models/vosk-model-small-en-us-0.15",
        "sample_rate": 16000,
    },
    "behavior": {
        "speak_replies": True,
        "cues": True,
        "start_minimized": False,
        "start_with_windows": False,
        "require_confirmation_for_power": True,
    },
    "paths": {
        "screenshot_dir": "",  # empty = Pictures/Ultron
    },
}


class Config:
    def __init__(self) -> None:
        self.path = data_dir() / "config.json"
        self.data: dict[str, Any] = copy.deepcopy(DEFAULTS)
        self.load()

    # ------------------------------------------------------------------ io
    def load(self) -> None:
        try:
            if self.path.exists():
                with open(self.path, "r", encoding="utf-8") as fh:
                    stored = json.load(fh)
                self.data = _deep_merge(self.data, stored)
        except Exception:
            from . import log

            log.get().exception("failed to read config; using defaults")

    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as fh:
                json.dump(self.data, fh, indent=2, ensure_ascii=False)
        except Exception:
            from . import log

            log.get().exception("failed to save config")

    # -------------------------------------------------------------- access
    def get(self, dotted: str, default: Any = None) -> Any:
        node: Any = self.data
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def set(self, dotted: str, value: Any) -> None:
        node = self.data
        parts = dotted.split(".")
        for part in parts[:-1]:
            nxt = node.setdefault(part, {})
            if not isinstance(nxt, dict):
                node[part] = {}
                nxt = node[part]
            node = nxt
        node[parts[-1]] = value

    def section(self, name: str) -> dict[str, Any]:
        return self.data.setdefault(name, {})


def _deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out
