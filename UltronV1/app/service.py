"""Assistant orchestration: wake word, state machine, command dispatch.

Threading model:
  * PortAudio thread  -> cheap callbacks (level, partial) + queued finals
  * worker thread     -> LLM decisions, command execution, state changes
  * TTS thread        -> synthesis + playback (suppresses the mic)
  * GUI thread        -> renders events from the bus
"""

from __future__ import annotations

import queue
import threading
import time
from collections import deque
from typing import Any

from . import audio_io, fallback, log
from .commands.executor import CONFIRM_REQUIRED, Executor
from .llm import Decision, OllamaBrain
from .stt import SpeechEngine
from .tts import Speaker

# Wake-word variants cover common Vosk mishearings.
_WAKE_VARIANTS = {
    "ultron": ("ultron", "altron", "oltron", "eltron", "ultra on", "ultrahn"),
}

STATES = ("standby", "listening", "thinking", "speaking")


class AssistantService:
    def __init__(self, cfg, bus) -> None:
        self.cfg = cfg
        self.bus = bus
        self.log = log.get()

        self.muted = False
        self._state = "standby"
        self._mode = "wake"  # 'wake' (listening for name) or 'capture' (taking a command)
        self._pending: tuple[str, dict] | None = None  # action awaiting confirmation
        self._confirm_deadline = 0.0
        self._history: deque[dict[str, str]] = deque(maxlen=16)
        self._inq: "queue.Queue[tuple[str, Any]]" = queue.Queue()
        self._stop = threading.Event()
        self._lock = threading.RLock()

        self.speaker = Speaker(cfg, on_speaking=self._on_speaking)
        self.executor = Executor(cfg, speak=self.notify)
        self.llm = OllamaBrain(cfg)
        self.stt: SpeechEngine | None = None

        self._hotkey_registered = False

    # ------------------------------------------------------------------ api
    def start(self) -> None:
        self.speaker.start()
        self.llm.refresh()
        self.bus.emit("llm_status", {
            "available": self.llm.available,
            "model": self.llm.model,
            "models": self.llm.models,
            "version": self.llm.version,
        })
        self._start_stt()
        self._register_hotkey()
        threading.Thread(target=self._worker, name="ultron-core", daemon=True).start()

    def shutdown(self) -> None:
        self._stop.set()
        self._inq.put(("exit", None))
        if self.stt:
            self.stt.stop()
        self.speaker.shutdown()
        self._unregister_hotkey()

    def notify(self, text: str) -> None:
        """Speak + log a line generated outside the normal flow (timers...)."""
        self.bus.emit("reply", text)
        if self.cfg.get("behavior.speak_replies", True):
            self.speaker.say(text)

    def submit_text(self, text: str) -> None:
        """Typed command from the GUI."""
        self._inq.put(("text", text.strip()))

    def hotkey_press(self) -> None:
        self._inq.put(("hotkey", None))

    def set_muted(self, muted: bool) -> None:
        self.muted = muted
        if self.stt:
            self.stt.suppressed = muted
        self.bus.emit("muted", muted)

    # ---------------------------------------------------------------- stt
    def _start_stt(self) -> None:
        from .modelfetch import have_model, model_path

        if not have_model():
            self.bus.emit("mic_error", "Speech model missing — open Settings to download it.")
            return

        self.stt = SpeechEngine(
            model_dir=model_path(),
            on_level=self._on_level,
            on_partial=self._on_partial,
            on_final=self._on_final,
            on_error=self._on_mic_error,
            sample_rate=int(self.cfg.get("stt.sample_rate", 16000)),
        )
        self.stt.start()

    def restart_stt(self) -> None:
        if self.stt:
            self.stt.stop()
            self.stt = None
        self._start_stt()

    # ------------------------------------------------------------ callbacks
    def _on_level(self, level: float) -> None:
        self.bus.emit("level", level)

    def _on_partial(self, text: str) -> None:
        self.bus.emit("partial", text)

    def _on_final(self, text: str) -> None:
        # Called from the audio thread: enqueue for the worker.
        self._inq.put(("final", text))

    def _on_mic_error(self, msg: str) -> None:
        self.bus.emit("mic_error", msg)
        self.log.error("mic: %s", msg)

    def _on_speaking(self, speaking: bool) -> None:
        if self.stt:
            self.stt.suppressed = speaking or self.muted
        if speaking:
            self._set_state("speaking")
        else:
            # small tail so playback reverb doesn't wake him
            time.sleep(0.25)
            with self._lock:
                if self._mode == "capture":
                    self._set_state("listening")
                else:
                    self._set_state("standby")

    # ------------------------------------------------------------- hotkeys
    def _register_hotkey(self) -> None:
        try:
            import keyboard

            keyboard.add_hotkey(self.cfg.get("hotkey", "ctrl+alt+u"), self.hotkey_press)
            self._hotkey_registered = True
        except Exception as exc:
            self.log.warning("hotkey registration failed: %s", exc)

    def _unregister_hotkey(self) -> None:
        if self._hotkey_registered:
            try:
                import keyboard

                keyboard.unhook_all()
            except Exception:
                pass
        self._hotkey_registered = False

    def apply_hotkey(self) -> None:
        self._unregister_hotkey()
        self._register_hotkey()

    # -------------------------------------------------------------- worker
    def _worker(self) -> None:
        while not self._stop.is_set():
            try:
                kind, payload = self._inq.get(timeout=0.25)
            except queue.Empty:
                # expire stale confirmation requests
                with self._lock:
                    if self._pending and time.time() > self._confirm_deadline:
                        self._pending = None
                        self._mode = "wake"
                        self._set_state("standby")
                continue
            if kind == "exit":
                break
            try:
                if kind == "final":
                    self._handle_final(payload)
                elif kind == "hotkey":
                    self._handle_hotkey()
                elif kind == "text":
                    self._handle_command(str(payload), source="text")
            except Exception:
                self.log.exception("worker error handling %s", kind)

    # ---------------------------------------------------------- wake logic
    def _wake_word(self) -> str:
        return str(self.cfg.get("wake_word", "ultron")).lower()

    def _matches_wake(self, text: str) -> bool:
        t = text.lower()
        word = self._wake_word()
        variants = _WAKE_VARIANTS.get(word, (word,))
        return any(v in t for v in variants)

    def _handle_final(self, text: str) -> None:
        if self.muted:
            return
        with self._lock:
            mode = self._mode
        if mode == "wake":
            if not self._matches_wake(text):
                self.log.debug("ignored (no wake word): %r", text)
                return
            if self.cfg.get("behavior.cues", True):
                audio_io.play(*audio_io.activation_cue())
            # Allow "ultron, open notepad" in a single breath:
            rest = self._strip_wake(text)
            if len(rest) >= 2:
                self._handle_command(rest, source="voice")
            else:
                self._mode = "capture"
                self._set_state("listening")
        else:  # capture
            self._handle_command(text, source="voice")

    def _strip_wake(self, text: str) -> str:
        t = text.lower()
        word = self._wake_word()
        variants = _WAKE_VARIANTS.get(word, (word,))
        for v in sorted(variants, key=len, reverse=True):
            if v in t:
                t = t.replace(v, " ")
                break
        cleaned = " ".join(t.replace(",", " ").split())
        return cleaned

    def _handle_hotkey(self) -> None:
        with self._lock:
            mode = self._mode
            speaking = self._state == "speaking"
        if speaking:
            self.speaker.stop_speech()
            return
        if mode == "wake":
            if self.cfg.get("behavior.cues", True):
                audio_io.play(*audio_io.activation_cue())
            self._mode = "capture"
            self._set_state("listening")
        else:
            self._mode = "wake"
            self._set_state("standby")

    # -------------------------------------------------------- command flow
    def _handle_command(self, text: str, source: str) -> None:
        text = text.strip()
        if not text:
            return
        self.bus.emit("user_said", text)

        # pending confirmation?
        with self._lock:
            pending = self._pending
            self._pending = None

        if pending is not None:
            action, params = pending
            if fallback.is_affirmative(text):
                self._set_state("thinking")
                outcome = self.executor.run(action, params)
                self.notify(outcome.detail or "Done.")
            elif fallback.is_negative(text):
                self.notify("Cancelled. A wise retreat.")
            else:
                # not clearly yes/no — keep waiting
                with self._lock:
                    self._pending = (action, params)
                    self._confirm_deadline = time.time() + 25.0
                self.notify("A simple yes or no will suffice.")
            self._mode = "wake"
            self._set_state("standby")
            return

        self._set_state("thinking")

        decision: Decision | None = None
        if self.llm.available or self.llm.refresh():
            decision = self.llm.decide(text, list(self._history))
        if decision is None:
            decision = fallback.parse(text)
            self.bus.emit("llm_status", {
                "available": False,
                "model": self.llm.model,
                "models": self.llm.models,
                "version": self.llm.version,
            })

        action = decision.action
        params = decision.params

        # 'cancel shutdown' style rescue
        if action in CONFIRM_REQUIRED and self.cfg.get("behavior.require_confirmation_for_power", True):
            with self._lock:
                self._pending = (action, params)
                self._confirm_deadline = time.time() + 25.0
                self._mode = "capture"
            self._set_state("listening")
            self.notify(decision.say + " Say yes to confirm, or no to cancel.")
            return

        outcome = self.executor.run(action, params) if action != "none" else None

        reply = decision.say
        if outcome is not None and outcome.detail:
            reply = (reply + " " + outcome.detail).strip()
        if not reply:
            reply = "Done."

        self._history.append({"role": "user", "content": text})
        self._history.append({"role": "assistant", "content": reply})

        if source == "voice":
            self._mode = "wake"  # after speaking, return to standby
        self.notify(reply)

    # ------------------------------------------------------------- states
    def _set_state(self, state: str) -> None:
        with self._lock:
            self._state = state
        self.bus.emit("state", state)

    @property
    def state(self) -> str:
        return self._state
