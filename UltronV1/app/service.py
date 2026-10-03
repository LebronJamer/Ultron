"""Assistant orchestration: wake word, state machine, command dispatch.

Threading model:
  * PortAudio thread  -> cheap callbacks (level, partial) + queued finals
  * worker thread     -> LLM decisions, command execution, state changes
  * TTS thread        -> synthesis + playback (suppresses the mic)
  * GUI thread        -> renders events from the bus

Recognition modes:
  * wake    : STT runs a grammar constrained to the trained wake-word
              variants (see stt.SpeechEngine) — highly reliable.
  * capture : full recognizer while a command is being dictated.
  * training: full recognizer, results are routed to the Voice Training
              Studio via bus events instead of the command pipeline.
"""

from __future__ import annotations

import queue
import threading
import time
from collections import deque
from typing import Any

from . import audio_io, fallback, log
from .commands.executor import CONFIRM_REQUIRED, Executor
from .custom_commands import match_custom_command, score
from .llm import Decision, OllamaBrain
from .stt import SpeechEngine
from .tts import Speaker

# Wake-word variants cover common Vosk mishearings; the Voice Training
# Studio adds the ones this specific user's microphone produces.
_WAKE_VARIANTS = {
    "ultron": ("ultron", "altron", "oltron", "eltron", "ultra on", "ultrahn"),
}

STATES = ("standby", "listening", "thinking", "speaking")

WAKE_FUZZY_THRESHOLD = 0.72


class AssistantService:
    def __init__(self, cfg, bus) -> None:
        self.cfg = cfg
        self.bus = bus
        self.log = log.get()

        self.muted = False
        self._state = "standby"
        self._mode = "wake"  # 'wake' (listening for name) or 'capture' (taking a command)
        self._training = False
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

    # ------------------------------------------------------------- training
    def begin_training(self) -> bool:
        """Route all recognized speech to the training studio."""
        if not self.stt or not self.stt.running:
            return False
        self._training = True
        self.stt.set_mode("capture")
        self._set_state("listening")
        return True

    def end_training(self) -> None:
        self._training = False
        if self.stt:
            self.stt.set_mode("wake")
        self._set_state("standby")

    # ----------------------------------------------------------- wake config
    def _wake_word(self) -> str:
        return str(self.cfg.get("wake_word", "ultron")).lower()

    def _wake_variants(self) -> list[str]:
        word = self._wake_word()
        variants = {word}
        variants.update(_WAKE_VARIANTS.get(word, ()))
        for v in self.cfg.get("wake.variants", []) or []:
            v = str(v).strip().lower()
            if len(v) >= 3:
                variants.add(v)
        return sorted(variants)

    def matches_wake(self, text: str) -> bool:
        """Public matcher used by the runtime and the training studio."""
        t = str(text or "").lower()
        if not t:
            return False
        variants = self._wake_variants()
        for v in variants:
            if v in t:
                return True
        word = self._wake_word()
        if len(word) >= 4 and score(t, word) >= WAKE_FUZZY_THRESHOLD:
            return True
        return any(score(t, v) >= 0.78 for v in variants if len(v) >= 5 and v != word)

    def apply_wake_settings(self) -> None:
        """Called after wake word / variants change — rebuilds the engine."""
        self.restart_stt()

    # ----------------------------------------------------------- audio setup
    def set_mic(self, device_index: int | None) -> None:
        self.cfg.set("stt.device", device_index)
        self.cfg.save()
        self.restart_stt()

    def set_stt_model(self, key: str) -> None:
        self.cfg.set("stt.model", key)
        self.cfg.save()
        self.restart_stt()

    def _start_stt(self) -> None:
        from .modelfetch import active_key, have_model, model_path

        key = active_key(self.cfg)
        if not have_model(key, self.cfg):
            self.bus.emit("mic_error", "Speech model missing — open TRAIN → Microphone & Model to download it.")
            return

        use_grammar = bool(self.cfg.get("stt.wake_grammar", True))
        self.stt = SpeechEngine(
            model_dir=model_path(key),
            on_level=self._on_level,
            on_partial=self._on_partial,
            on_final=self._on_final,
            on_error=self._on_mic_error,
            sample_rate=int(self.cfg.get("stt.sample_rate", 16000)),
            device=self.cfg.get("stt.device", None),
            wake_phrases=self._wake_variants() if use_grammar else None,
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
        if self._training:
            self.bus.emit("train_partial", text)
        else:
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
                if self._training:
                    self._set_state("listening")
                elif self._mode == "capture":
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
                        self._enter_wake()
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
    def _enter_capture(self) -> None:
        with self._lock:
            self._mode = "capture"
        if self.stt:
            self.stt.set_mode("capture")

    def _enter_wake(self) -> None:
        with self._lock:
            self._mode = "wake"
        if self.stt:
            self.stt.set_mode("wake")

    def _handle_final(self, text: str) -> None:
        if self._training:
            # Training studio owns the transcript.
            self.bus.emit("train_final", text)
            return
        if self.muted:
            return
        with self._lock:
            mode = self._mode
        if mode == "wake":
            if not self.matches_wake(text):
                self.log.debug("ignored (no wake word): %r", text)
                return
            if self.cfg.get("behavior.cues", True):
                audio_io.play(*audio_io.activation_cue())
            # Allow "ultron, open notepad" in a single breath:
            rest = self._strip_wake(text)
            if len(rest) >= 2:
                self._handle_command(rest, source="voice")
            else:
                self._enter_capture()
                self._set_state("listening")
        else:  # capture
            self._handle_command(text, source="voice")

    def _strip_wake(self, text: str) -> str:
        t = text.lower()
        variants = sorted(self._wake_variants(), key=len, reverse=True)
        for v in variants:
            if v in t:
                t = t.replace(v, " ")
                break
        cleaned = " ".join(t.replace(",", " ").split())
        return cleaned

    def _handle_hotkey(self) -> None:
        if self._training:
            return
        with self._lock:
            mode = self._mode
            speaking = self._state == "speaking"
        if speaking:
            self.speaker.stop_speech()
            return
        if mode == "wake":
            if self.cfg.get("behavior.cues", True):
                audio_io.play(*audio_io.activation_cue())
            self._enter_capture()
            self._set_state("listening")
        else:
            self._enter_wake()
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
            self._enter_wake()
            self._set_state("standby")
            return

        self._set_state("thinking")

        decision: Decision | None = None

        # 1) trained custom commands take priority — instant and deterministic
        custom = match_custom_command(text, self.cfg.get("custom_commands", []) or [])
        if custom is not None:
            cc, phrase, _sc = custom
            self.bus.emit("custom_match", {"name": cc.get("name", ""), "phrase": phrase})
            decision = Decision(
                action=str(cc.get("action", "none") or "none"),
                params=cc.get("params") or {},
                say=str(cc.get("reply", "") or ""),
            )
        else:
            # 2) the local LLM brain
            if self.llm.available or self.llm.refresh():
                decision = self.llm.decide(text, list(self._history))
            # 3) offline fallback parser
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
            self._enter_capture()
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
            self._enter_wake()  # after speaking, return to standby
        self.notify(reply)

    # ------------------------------------------------------------- states
    def _set_state(self, state: str) -> None:
        with self._lock:
            self._state = state
        self.bus.emit("state", state)

    @property
    def state(self) -> str:
        return self._state
