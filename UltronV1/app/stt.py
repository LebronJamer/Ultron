"""Continuous offline speech recognition with Vosk — dual-mode.

wake mode    : a grammar-constrained recognizer that can only output the
               trained wake-word phrases. Constrained decoding makes wake
               detection dramatically more reliable (background speech
               cannot drift into random words). Falls back to the full
               recognizer when no grammar is configured.
capture mode : the full recognizer, used while taking a command and during
               voice training.

Runs a sounddevice InputStream in a dedicated thread; Vosk runs inside the
PortAudio callback (the pattern used by the official Vosk examples).
Callbacks are invoked from the audio thread — keep them cheap.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Callable


def list_input_devices() -> list[tuple[int, str]]:
    """[(index, name)] of microphone input devices."""
    try:
        import sounddevice as sd

        return [
            (i, d["name"])
            for i, d in enumerate(sd.query_devices())
            if int(d.get("max_input_channels", 0)) > 0
        ]
    except Exception:
        return []


class SpeechEngine:
    def __init__(
        self,
        model_dir: Path,
        on_level: Callable[[float], None],
        on_partial: Callable[[str], None],
        on_final: Callable[[str], None],
        on_error: Callable[[str], None],
        sample_rate: int = 16000,
        device: int | None = None,
        wake_phrases: list[str] | None = None,
    ) -> None:
        self.model_dir = Path(model_dir)
        self.sample_rate = sample_rate
        self.device = device
        self.wake_phrases = [p for p in (wake_phrases or []) if p]
        self._on_level = on_level
        self._on_partial = on_partial
        self._on_final = on_final
        self._on_error = on_error
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._model = None
        self._rec_wake: object | None = None
        self._rec_full: object | None = None
        self._lock = threading.Lock()
        # While True, incoming audio is dropped (stops Ultron hearing his
        # own voice through the speakers).
        self.suppressed = False
        self.mode = "wake"  # 'wake' | 'capture'
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

    def set_mode(self, mode: str) -> None:
        """Switch between 'wake' (grammar) and 'capture' (full) decoding."""
        with self._lock:
            if mode == self.mode:
                return
            self.mode = mode
            need_wake = mode == "wake" and bool(self.wake_phrases)
        if need_wake:
            # Rebuild the grammar recognizer so no stale audio state leaks
            # across the mode switch.
            try:
                rec = self._make_grammar_rec()
                with self._lock:
                    self._rec_wake = rec
            except Exception:
                from . import log

                log.get().debug("wake recognizer rebuild failed; using full recognizer")

    # ------------------------------------------------------------- worker
    def _make_grammar_rec(self):
        from vosk import KaldiRecognizer

        try:
            return KaldiRecognizer(self._model, self.sample_rate, json.dumps(self.wake_phrases))
        except Exception:
            from . import log

            log.get().debug("grammar recognizer unsupported; falling back to full")
            return None

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

        with self._lock:
            self._model = model
            self._rec_full = KaldiRecognizer(model, self.sample_rate)
            self._rec_wake = self._make_grammar_rec() if self.wake_phrases else None

        def callback(indata, frames, time_info, status) -> None:
            try:
                if status:
                    pass  # xruns are non-fatal
                rms = float(np.sqrt(np.mean((indata.astype(np.float32) / 32768.0) ** 2)))
                self._on_level(min(1.0, rms * 6.0))
                if self.suppressed or self._stop.is_set():
                    return
                with self._lock:
                    if self.mode == "wake" and self._rec_wake is not None:
                        rec = self._rec_wake
                    else:
                        rec = self._rec_full
                if rec is None:
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
                device=self.device,
                callback=callback,
            ):
                while not self._stop.is_set():
                    self._stop.wait(0.2)
        except Exception as exc:
            self._on_error(f"microphone error: {exc}")
        finally:
            self.running = False
