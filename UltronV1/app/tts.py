"""Speech output worker: SAPI synthesis -> ULTRON FX chain -> playback."""

from __future__ import annotations

import queue
import threading
from typing import Callable

import numpy as np

from . import audio_io, fx, log


class Speaker:
    """Owns the TTS thread. ``on_speaking(bool)`` brackets playback so the
    microphone can be muted to prevent Ultron hearing himself."""

    def __init__(self, cfg, on_speaking: Callable[[bool], None]) -> None:
        self.cfg = cfg
        self._on_speaking = on_speaking
        self._q: "queue.Queue[str | None]" = queue.Queue()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._synth = None  # SapiSynth, lazy (Windows only)

    # ---------------------------------------------------------------- api
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="ultron-tts", daemon=True)
        self._thread.start()

    def say(self, text: str) -> None:
        if not text:
            return
        self._q.put(text)

    def stop_speech(self) -> None:
        """Drop queued lines and cut current playback."""
        try:
            while True:
                self._q.get_nowait()
        except queue.Empty:
            pass
        audio_io.stop()

    def shutdown(self) -> None:
        self.stop_speech()
        self._q.put(None)
        if self._thread:
            self._thread.join(timeout=3.0)

    # ------------------------------------------------------------- worker
    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                item = self._q.get(timeout=0.2)
            except queue.Empty:
                continue
            if item is None:
                break
            try:
                self._speak(item)
            except Exception:
                log.get().exception("speak failed")

    def _speak(self, text: str) -> None:
        # Local imports keep non-Windows dev runs importable.
        from .tts_sapi import SapiSynth

        if self._synth is None:
            self._synth = SapiSynth()

        result = self._synth.synth(text, self.cfg)
        if result is None:
            self._on_speaking(True)
            data, sr = audio_io.error_cue()
            audio_io.play(data, sr, blocking=True)
            self._on_speaking(False)
            return

        raw, sr = result
        vcfg = self.cfg.get("voice", {})
        processed = fx.ultronize(
            raw,
            sr,
            intensity=float(vcfg.get("fx_intensity", 1.0)),
            extra_pitch_semitones=float(vcfg.get("fx_pitch_semitones", 2.5)),
        )
        processed = processed * float(vcfg.get("volume", 0.9))

        self._on_speaking(True)
        try:
            audio_io.play(processed, sr, blocking=True)
        finally:
            self._on_speaking(False)
