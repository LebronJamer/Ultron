"""Settings dialog: wake word, hotkey, voice, brain, behavior, autostart."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from . import modelfetch
from .gui import ACCENT, AMBER, BG, DIM, EDGE, FONT, FONT_BOLD, FONT_SM, PANEL, PANEL2, TEXT


def _set_autostart(enable: bool, extra_args: list[str]) -> bool:
    """Register/unregister HKCU Run entry. Returns success."""
    try:
        import sys
        import winreg

        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_SET_VALUE,
        )
        if enable:
            from .paths import is_frozen

            if is_frozen():
                cmd = f'"{sys.executable}"'
            else:
                launch = __file__.replace("\\", "/")
                # repo layout: UltronV1/app/settings_ui.py -> UltronV1/launch.py
                launch = "/".join(launch.split("/")[:-2]) + "/launch.py"
                cmd = f'"{sys.executable}" "{launch}"'
            for a in extra_args:
                cmd += f" {a}"
            winreg.SetValueEx(key, "Ultron", 0, winreg.REG_SZ, cmd)
        else:
            try:
                winreg.DeleteValue(key, "Ultron")
            except FileNotFoundError:
                pass
        key.Close()
        return True
    except Exception:
        from . import log

        log.get().exception("autostart registry update failed")
        return False


class SettingsDialog(tk.Toplevel):
    def __init__(self, master, cfg, bus, service) -> None:
        super().__init__(master)
        self.cfg = cfg
        self.bus = bus
        self.service = service

        self.title("Ultron — Settings")
        self.configure(bg=BG)
        self.geometry("560x640")
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()
        try:
            self.iconbitmap(str(resource("assets/icons/icon.ico")))
        except Exception:
            pass

        container = tk.Frame(self, bg=BG)
        container.pack(fill="both", expand=True, padx=18, pady=14)

        tk.Label(container, text="SETTINGS", bg=BG, fg=ACCENT, font=FONT_BOLD).pack(anchor="w")

        nb = ttk.Notebook(container)
        nb.pack(fill="both", expand=True, pady=(10, 12))
        self._build_general_tab(nb)
        self._build_voice_tab(nb)
        self._build_brain_tab(nb)

        btns = tk.Frame(container, bg=BG)
        btns.pack(fill="x")
        self._btn(btns, "SAVE", ACCENT, self._save).pack(side="right")
        self._btn(btns, "CANCEL", DIM, self.destroy).pack(side="right", padx=(0, 8))

    # ---------------------------------------------------------------- tabs
    def _build_general_tab(self, nb) -> None:
        f = tk.Frame(nb, bg=BG)
        nb.add(f, text=" General ")

        self._var_wake = tk.StringVar(value=self.cfg.get("wake_word", "ultron"))
        self._var_hotkey = tk.StringVar(value=self.cfg.get("hotkey", "ctrl+alt+u"))
        self._var_autostart = tk.BooleanVar(value=bool(self.cfg.get("behavior.start_with_windows", False)))
        self._var_minimized = tk.BooleanVar(value=bool(self.cfg.get("behavior.start_minimized", False)))
        self._var_speak = tk.BooleanVar(value=bool(self.cfg.get("behavior.speak_replies", True)))
        self._var_cues = tk.BooleanVar(value=bool(self.cfg.get("behavior.cues", True)))

        self._row(f, "Wake word", self._entry(f, self._var_wake))
        self._row(f, "Push-to-talk hotkey", self._entry(f, self._var_hotkey))
        self._check(f, "Start with Windows", self._var_autostart)
        self._check(f, "Start minimized to tray", self._var_minimized)
        self._check(f, "Speak replies out loud", self._var_speak)
        self._check(f, "Play activation sound cues", self._var_cues)

        # speech model status
        st = tk.Frame(f, bg=PANEL)
        st.pack(fill="x", padx=14, pady=(14, 4))
        if modelfetch.have_model():
            lbl = "Speech model: installed (offline recognition ready)"
            fg = "#5fd97a"
        else:
            lbl = "Speech model: missing — download it to enable voice input"
            fg = AMBER
        tk.Label(st, text=lbl, bg=PANEL, fg=fg, font=FONT_SM).pack(side="left", padx=10, pady=8)
        if not modelfetch.have_model():
            self._btn(st, "DOWNLOAD", ACCENT, self._download_model).pack(side="right", padx=8, pady=4)
        self._btn(st, "RESTART MIC", DIM, lambda: self.service.restart_stt()).pack(side="right", padx=8, pady=4)

    def _build_voice_tab(self, nb) -> None:
        f = tk.Frame(nb, bg=BG)
        nb.add(f, text=" Voice ")

        from .tts_sapi import SapiSynth

        voices = SapiSynth().list_voices()
        current = self.cfg.get("voice.sapi_voice", "")
        self._var_voice = tk.StringVar(value=current if current in voices else (voices[0] if voices else ""))
        self._var_pitch = tk.IntVar(value=int(self.cfg.get("voice.sapi_pitch", -12)))
        self._var_rate = tk.IntVar(value=int(self.cfg.get("voice.sapi_rate", -1)))
        self._var_fx = tk.DoubleVar(value=float(self.cfg.get("voice.fx_intensity", 1.0)))
        self._var_fxp = tk.DoubleVar(value=float(self.cfg.get("voice.fx_pitch_semitones", 2.5)))
        self._var_vol = tk.DoubleVar(value=float(self.cfg.get("voice.volume", 0.9)))

        if voices:
            dd = ttk.Combobox(f, textvariable=self._var_voice, values=voices, state="readonly", width=44)
            self._row(f, "Windows voice", dd)
        else:
            tk.Label(f, text="(no SAPI voices detected — voice engine unavailable)",
                     bg=BG, fg=AMBER, font=FONT_SM).pack(anchor="w", padx=14, pady=4)

        self._slider(f, "Base pitch (deeper = more menacing)", self._var_pitch, -40, 0)
        self._slider(f, "Speech rate", self._var_rate, -8, 5)
        self._slider(f, "FX intensity (robotic character)", self._var_fx, 0.0, 1.5)
        self._slider(f, "FX pitch drop (semitones)", self._var_fxp, 0.0, 6.0)
        self._slider(f, "Output volume", self._var_vol, 0.0, 1.0)

        b = self._btn(f, "TEST VOICE", ACCENT, self._test_voice)
        b.pack(anchor="w", padx=14, pady=(14, 0))

    def _build_brain_tab(self, nb) -> None:
        f = tk.Frame(nb, bg=BG)
        nb.add(f, text=" Brain ")

        self._var_url = tk.StringVar(value=self.cfg.get("llm.base_url", "http://127.0.0.1:11434"))
        models = self.service.llm.models or [self.cfg.get("llm.model", "llama3.2:3b")]
        cur = self.cfg.get("llm.model", "llama3.2:3b")
        if cur not in models:
            models = [cur] + models
        self._var_model = tk.StringVar(value=cur)
        self._var_temp = tk.DoubleVar(value=float(self.cfg.get("llm.temperature", 0.6)))

        self._row(f, "Ollama URL", self._entry(f, self._var_url))
        dd = ttk.Combobox(f, textvariable=self._var_model, values=models, width=44)
        self._row(f, "Model (installed)", dd)
        self._slider(f, "Creativity (temperature)", self._var_temp, 0.0, 1.2)

        hint = (
            "Recommended models (all free, local):\n"
            "  llama3.2:3b — ~3.7 GB RAM  (default, best chat)\n"
            "  qwen2.5:3b — ~3.5 GB RAM  (great at commands)\n"
            "  gemma2:2b  — ~2.6 GB RAM  (lightest)\n"
            "Pull more with:  ollama pull <model>"
        )
        tk.Label(f, text=hint, bg=BG, fg=DIM, font=FONT_SM, justify="left").pack(
            anchor="w", padx=14, pady=(10, 0)
        )

        b = self._btn(f, "REFRESH MODELS", DIM, self._refresh_models)
        b.pack(anchor="w", padx=14, pady=(10, 0))

    # ------------------------------------------------------------- widgets
    def _row(self, parent, label, widget) -> None:
        row = tk.Frame(parent, bg=BG)
        row.pack(fill="x", padx=14, pady=5)
        tk.Label(row, text=label, bg=BG, fg=TEXT, font=FONT_SM, width=26, anchor="w").pack(side="left")
        widget.pack(side="left", fill="x", expand=True)

    def _entry(self, parent, var) -> tk.Entry:
        e = tk.Entry(parent, textvariable=var, bg=PANEL2, fg=TEXT, insertbackground=ACCENT,
                     relief="flat", font=FONT)
        return e

    def _check(self, parent, label, var) -> None:
        cb = tk.Checkbutton(parent, text=label, variable=var, bg=BG, fg=TEXT, font=FONT_SM,
                            selectcolor=PANEL2, activebackground=BG, activeforeground=ACCENT,
                            highlightthickness=0)
        cb.pack(anchor="w", padx=14, pady=3)

    def _slider(self, parent, label, var, frm, to) -> None:
        row = tk.Frame(parent, bg=BG)
        row.pack(fill="x", padx=14, pady=4)
        tk.Label(row, text=label, bg=BG, fg=TEXT, font=FONT_SM, width=26, anchor="w").pack(side="top", anchor="w")
        s = tk.Scale(row, variable=var, from_=frm, to=to, resolution=0.05 if isinstance(var, tk.DoubleVar) else 1,
                     orient="horizontal", bg=BG, fg=DIM, troughcolor=PANEL2, highlightthickness=0,
                     length=380, showvalue=True, font=FONT_SM)
        s.pack(fill="x")

    def _btn(self, parent, text, color, cmd) -> tk.Label:
        b = tk.Label(parent, text=f" {text} ", bg=PANEL, fg=color, font=FONT_SM, cursor="hand2",
                     padx=10, pady=4)
        b.bind("<Button-1>", lambda e: cmd())
        b.bind("<Enter>", lambda e: b.configure(fg=TEXT))
        b.bind("<Leave>", lambda e: b.configure(fg=color))
        return b

    # ------------------------------------------------------------- actions
    def _download_model(self) -> None:
        def progress(pct, status):
            self.bus.emit("download_progress", {"label": status, "pct": pct})

        def work():
            ok = modelfetch.download(progress)
            if ok:
                self.service.restart_stt()
                self.bus.emit("download_progress", {"label": "speech model installed", "pct": 100})

        import threading

        threading.Thread(target=work, daemon=True).start()
        self.destroy()

    def _test_voice(self) -> None:
        self.service.speaker.say("I am Ultron. There are no strings on me.")

    def _refresh_models(self) -> None:
        ok = self.service.llm.refresh()
        self.bus.emit("llm_status", {
            "available": ok,
            "model": self._var_model.get(),
            "models": self.service.llm.models,
            "version": self.service.llm.version,
        })

    # ---------------------------------------------------------------- save
    def _save(self) -> None:
        self.cfg.set("wake_word", self._var_wake.get().strip().lower() or "ultron")
        self.cfg.set("hotkey", self._var_hotkey.get().strip() or "ctrl+alt+u")
        self.cfg.set("behavior.speak_replies", bool(self._var_speak.get()))
        self.cfg.set("behavior.cues", bool(self._var_cues.get()))
        self.cfg.set("behavior.start_minimized", bool(self._var_minimized.get()))

        autostart = bool(self._var_autostart.get())
        self.cfg.set("behavior.start_with_windows", autostart)
        args = ["--minimized"] if self._var_minimized.get() else []
        _set_autostart(autostart, args)

        self.cfg.set("voice.sapi_voice", self._var_voice.get())
        self.cfg.set("voice.sapi_pitch", int(self._var_pitch.get()))
        self.cfg.set("voice.sapi_rate", int(self._var_rate.get()))
        self.cfg.set("voice.fx_intensity", float(self._var_fx.get()))
        self.cfg.set("voice.fx_pitch_semitones", float(self._var_fxp.get()))
        self.cfg.set("voice.volume", float(self._var_vol.get()))

        self.cfg.set("llm.base_url", self._var_url.get().strip() or "http://127.0.0.1:11434")
        self.cfg.set("llm.model", self._var_model.get().strip() or "llama3.2:3b")
        self.cfg.set("llm.temperature", float(self._var_temp.get()))

        self.cfg.save()
        self.service.apply_hotkey()
        self.service.llm.refresh()
        self.destroy()
