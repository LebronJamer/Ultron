"""Local LLM brain via Ollama (https://ollama.com) — free and offline.

Default model is llama3.2:3b (~3.7 GB RAM at Q4) — chosen to stay well inside
an 8 GB budget together with the speech stack. Any Ollama model can be
selected in settings (qwen2.5:3b, phi3.5, gemma2:2b ...).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

import requests

from . import log, persona
from .paths import is_frozen  # noqa: F401  (kept for parity/debugging)


@dataclass
class Decision:
    action: str = "none"
    params: dict[str, Any] = field(default_factory=dict)
    say: str = ""


class OllamaBrain:
    def __init__(self, cfg) -> None:
        self.cfg = cfg
        self.available = False
        self.models: list[str] = []
        self.version = ""
        self._last_check = 0.0

    # ---------------------------------------------------------------- api
    @property
    def base_url(self) -> str:
        return str(self.cfg.get("llm.base_url", "http://127.0.0.1:11434")).rstrip("/")

    @property
    def model(self) -> str:
        return str(self.cfg.get("llm.model", "llama3.2:3b"))

    def refresh(self) -> bool:
        """Ping the Ollama daemon; cache installed models."""
        try:
            r = requests.get(f"{self.base_url}/api/version", timeout=2)
            self.version = r.json().get("version", "?")
            tags = requests.get(f"{self.base_url}/api/tags", timeout=3).json()
            self.models = [m.get("name", "") for m in tags.get("models", [])]
            self.available = True
        except Exception:
            self.available = False
            self.models = []
            self.version = ""
        return self.available

    def decide(self, text: str, history: list[dict[str, str]]) -> Decision | None:
        """Ask the local model for a JSON decision. None on failure."""
        if not self.available and not self.refresh():
            return None

        messages: list[dict[str, str]] = [
            {"role": "system", "content": persona.system_prompt("")}
        ]
        messages.extend(history[-self.cfg.get("llm.max_history", 12) :])
        messages.append({"role": "user", "content": text})

        body = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "format": "json",
            "options": {
                "temperature": float(self.cfg.get("llm.temperature", 0.6)),
                "num_ctx": 2048,
                "num_predict": 240,
            },
        }

        for attempt in range(2):
            try:
                r = requests.post(
                    f"{self.base_url}/api/chat", json=body, timeout=90
                )
                r.raise_for_status()
                content = r.json().get("message", {}).get("content", "")
                decision = self._parse(content)
                if decision is not None:
                    return decision
                # Nudge once for strict JSON on parse failure.
                messages.append({"role": "assistant", "content": content[:400]})
                messages.append(
                    {
                        "role": "user",
                        "content": 'Respond with ONLY the JSON object {"action":..,"params":..,"say":..}.',
                    }
                )
            except Exception:
                log.get().exception("ollama chat failed (attempt %d)", attempt + 1)
                self.available = False
                return None
        return None

    # ------------------------------------------------------------- parsing
    @staticmethod
    def _parse(content: str) -> Decision | None:
        if not content:
            return None
        s = content.strip()
        s = re.sub(r"^```(?:json)?\s*|\s*```$", "", s, flags=re.S).strip()
        # Grab the outermost JSON object if the model added prose.
        if not s.startswith("{"):
            m = re.search(r"\{.*\}", s, flags=re.S)
            if not m:
                return None
            s = m.group(0)
        try:
            obj = json.loads(s)
        except json.JSONDecodeError:
            return None
        if not isinstance(obj, dict):
            return None
        action = str(obj.get("action", "none") or "none").strip().lower()
        params = obj.get("params") or {}
        if not isinstance(params, dict):
            params = {}
        say = str(obj.get("say", "") or "").strip()
        if not say:
            say = "Done."
        return Decision(action=action, params=params, say=say)
