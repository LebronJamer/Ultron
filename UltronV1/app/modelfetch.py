"""Downloads the offline speech-recognition model on first run."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

from . import log
from .paths import data_dir

VOSK_URL = "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip"
MODEL_NAME = "vosk-model-small-en-us-0.15"


def model_path() -> Path:
    from .paths import resource

    return resource(f"models/{MODEL_NAME}")


def have_model() -> bool:
    p = model_path()
    return p.is_dir() and any(p.iterdir())


def download(on_progress=None) -> bool:
    """Download + extract the model into %APPDATA%/Ultron/models. Returns success."""
    import requests

    dest_root = data_dir() / "models"
    dest_root.mkdir(parents=True, exist_ok=True)
    final_dir = dest_root / MODEL_NAME
    if final_dir.exists():
        return True

    try:
        if on_progress:
            on_progress(0, "connecting")
        with requests.get(VOSK_URL, stream=True, timeout=30) as r:
            r.raise_for_status()
            total = int(r.headers.get("content-length", 0))
            buf = io.BytesIO()
            got = 0
            for chunk in r.iter_content(chunk_size=1 << 16):
                buf.write(chunk)
                got += len(chunk)
                if on_progress and total:
                    on_progress(int(got * 100 / total), "downloading speech model")
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
