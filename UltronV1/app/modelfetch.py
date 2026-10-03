"""Offline speech-recognition model management.

Two Vosk models are supported:
  small  — vosk-model-small-en-us-0.15  (~40 MB)   default, fast
  large  — vosk-model-en-us-0.22         (~1.3 GB) noticeably more accurate

Models live in %APPDATA%/Ultron/models when downloaded at runtime, or are
bundled from app/models/ in the installed build.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

from . import log
from .paths import data_dir, resource

MODEL_CATALOG: dict[str, dict] = {
    "small": {
        "label": "Small — 40 MB, fast (default)",
        "dir": "vosk-model-small-en-us-0.15",
        "url": "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip",
        "size_mb": 40,
    },
    "large": {
        "label": "Large — 1.3 GB, most accurate (recommended if detection is poor)",
        "dir": "vosk-model-en-us-0.22",
        "url": "https://alphacephei.com/vosk/models/vosk-model-en-us-0.22.zip",
        "size_mb": 1300,
    },
}

# Kept for backward compatibility with the original single-model code.
VOSK_URL = MODEL_CATALOG["small"]["url"]
MODEL_NAME = MODEL_CATALOG["small"]["dir"]


def active_key(cfg) -> str:
    key = str(cfg.get("stt.model", "small") or "small").lower()
    return key if key in MODEL_CATALOG else "small"


def model_path(key: str | None = None) -> Path:
    key = key if key in MODEL_CATALOG else "small"
    return resource(f"models/{MODEL_CATALOG[key]['dir']}")


def have_model(key: str | None = None, cfg=None) -> bool:
    """Is the given (or active) model present? Prefers the bundled copy."""
    k = key or (active_key(cfg) if cfg is not None else "small")
    p = model_path(k)
    if p.is_dir() and any(p.iterdir()):
        return True
    # fall back to the per-user copy (downloaded at runtime)
    user = data_dir() / "models" / MODEL_CATALOG[k]["dir"]
    return user.is_dir() and any(user.iterdir())


def download(on_progress=None, key: str | None = None, cfg=None) -> bool:
    """Download + extract a model into %APPDATA%/Ultron/models. Returns success."""
    import requests

    k = key or (active_key(cfg) if cfg is not None else "small")
    info = MODEL_CATALOG[k]
    dest_root = data_dir() / "models"
    dest_root.mkdir(parents=True, exist_ok=True)
    final_dir = dest_root / info["dir"]
    if final_dir.exists() and any(final_dir.iterdir()):
        return True

    try:
        if on_progress:
            on_progress(0, f"connecting ({info['size_mb']} MB)")
        with requests.get(info["url"], stream=True, timeout=60) as r:
            r.raise_for_status()
            total = int(r.headers.get("content-length", 0))
            buf = io.BytesIO()
            got = 0
            last_pct = -1
            for chunk in r.iter_content(chunk_size=1 << 16):
                buf.write(chunk)
                got += len(chunk)
                if on_progress and total:
                    pct = int(got * 100 / total)
                    if pct != last_pct:
                        last_pct = pct
                        on_progress(pct, f"downloading {info['label'].split(' — ')[0].lower()} model")
        if on_progress:
            on_progress(100, "extracting")
        with zipfile.ZipFile(buf) as zf:
            zf.extractall(dest_root)
        if on_progress:
            on_progress(100, "done")
        return final_dir.exists()
    except Exception:
        log.get().exception("model download failed")
        if on_progress:
            on_progress(-1, "failed")
        return False
