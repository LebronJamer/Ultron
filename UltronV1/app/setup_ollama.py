"""Guided first-run setup for the Ollama local LLM daemon."""

from __future__ import annotations

import re
import subprocess
import webbrowser

from . import log
from .llm import OllamaBrain

CREATE_NO_WINDOW = 0x08000000
CREATE_NEW_CONSOLE = 0x00000010

RECOMMENDED_MODELS = [
    ("llama3.2:3b", "~2.0 GB download / ~3.7 GB RAM — recommended, best conversation"),
    ("qwen2.5:3b", "~1.9 GB download / ~3.5 GB RAM — strong at structured commands"),
    ("gemma2:2b", "~1.6 GB download / ~2.6 GB RAM — lightest full brain"),
    ("phi3.5:3.8b", "~2.2 GB download / ~4.0 GB RAM — good reasoning"),
]


def check(cfg) -> tuple[bool, str, list[str]]:
    """Return (daemon_running, version, installed_model_names)."""
    brain = OllamaBrain(cfg)
    ok = brain.refresh()
    return ok, brain.version, brain.models


def open_download_page() -> None:
    webbrowser.open("https://ollama.com/download")


def install_with_winget() -> bool:
    """Launch winget in a visible console so the user sees progress."""
    try:
        subprocess.Popen(
            [
                "winget", "install", "--id", "Ollama.Ollama", "-e",
                "--accept-source-agreements", "--accept-package-agreements",
            ],
            creationflags=CREATE_NEW_CONSOLE,
        )
        return True
    except FileNotFoundError:
        log.get().warning("winget not available")
        return False
    except Exception:
        log.get().exception("winget install failed to launch")
        return False


def pull_model(model: str, progress) -> None:
    """Run `ollama pull <model>`, streaming percent progress to callback.

    ``progress(pct:int, status:str)`` — pct is -1 on failure, 100 when done.
    Runs synchronously; call from a worker thread.
    """
    try:
        proc = subprocess.Popen(
            ["ollama", "pull", model],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=CREATE_NO_WINDOW,
        )
        assert proc.stderr is not None
        last = ""
        for line in proc.stderr:
            line = line.strip()
            if not line:
                continue
            last = line
            m = re.search(r"(\d+)%", line)
            if m:
                progress(int(m.group(1)), line)
            else:
                progress(-2, line)  # informational
        code = proc.wait()
        if code == 0:
            progress(100, "done")
        else:
            progress(-1, last or f"ollama exited with code {code}")
    except FileNotFoundError:
        progress(-1, "The 'ollama' command was not found. Install Ollama first.")
    except Exception as exc:
        log.get().exception("pull failed")
        progress(-1, str(exc))
