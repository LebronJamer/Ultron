"""Continuous offline speech recognition with Vosk.

Runs a sounddevice InputStream in a dedicated thread; Vosk runs inside the
PortAudio callback (this is the pattern used by the official Vosk examples).
Callbacks are invoked from the audio thread — keep them cheap.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Callable


class SpeechEngine:
    def __init__(
        self,
        model_dir: Path,
        on_level: Callable[[float], None],
        on_partial: Callable[[str], None],
        on_final: Callable[[str], None],
        on_error: Callable[[str], None],
        sample_rate: int = 16000,
    ) -> None:
        self.model_dir = Path(model_dir)
        self.sample_rate = sample_rate
        self._on_level = on_level
        self._on_partial = on_partial
        self._on_final = on_final
        self._on_error = on_error
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        # While True, incoming audio is dropped (used to stop Ultron from
        # hearing his own voice through the speakers).
        self.suppressed = False
        self.running = False

    # ---------------------------------------------------------------- api
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="ultron-stt", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3.0)
        self.running = False

    # ------------------------------------------------------------- worker
    def _run(self) -> None:
        import numpy as np

        try:
            import sounddevice as sd
            from vosk import KaldiRecognizer, Model
        except Exception as exc:  # pragma: no cover
            self._on_error(f"missing audio/STT dependency: {exc}")
            return

        if not self.model_dir.exists():
            self._on_error(f"speech model not found: {self.model_dir}")
            return

        try:
            model = Model(str(self.model_dir))
        except Exception as exc:
            self._on_error(f"failed to load speech model: {exc}")
            return

        rec = KaldiRecognizer(model, self.sample_rate)

        def callback(indata, frames, time_info, status) -> None:
            try:
                if status:
                    pass  # xruns are non-fatal
                rms = float(np.sqrt(np.mean((indata.astype(np.float32) / 32768.0) ** 2)))
                self._on_level(min(1.0, rms * 6.0))
                if self.suppressed or self._stop.is_set():
                    return
                if rec.AcceptWaveform(indata.tobytes()):
                    text = json.loads(rec.Result()).get("text", "").strip()
                    if text:
                        self._on_final(text)
                else:
                    partial = json.loads(rec.PartialResult()).get("partial", "").strip()
                    if partial:
                        self._on_partial(partial)
            except Exception:  # never kill the audio thread
                from . import log

                log.get().exception("STT callback error")

        self.running = True
        try:
            with sd.InputStream(
                samplerate=self.sample_rate,
                blocksize=2000,
                dtype="int16",
                channels=1,
                callback=callback,
            ):
                while not self._stop.is_set():
                    self._stop.wait(0.2)
        except Exception as exc:
            self._on_error(f"microphone error: {exc}")
        finally:
            self.running = False
