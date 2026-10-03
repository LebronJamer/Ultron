"""Guided first-run wizard: voice check -> brain (Ollama) setup -> done."""

from __future__ import annotations

import threading
import tkinter as tk
from tkinter import ttk

from . import modelfetch, setup_ollama
from .gui import ACCENT, AMBER, BG, DIM, FONT, FONT_BOLD, FONT_SM, PANEL, PANEL2, TEXT


class FirstRunWizard(tk.Toplevel):
    STEPS = ("welcome", "voice", "brain", "done")

    def __init__(self, master, cfg, bus, service) -> None:
        super().__init__(master)
        self.cfg = cfg
        self.bus = bus
        self.service = service
        self._step = "welcome"

        self.title("Ultron — First run")
        self.configure(bg=BG)
        self.geometry("620x520")
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()

        self._body = tk.Frame(self, bg=BG)
        self._body.pack(fill="both", expand=True, padx=24, pady=20)
        self._nav = tk.Frame(self, bg=BG)
        self._nav.pack(fill="x", padx=24, pady=(0, 18))

        self._render()

    # ------------------------------------------------------------ plumbing
    def _clear(self) -> None:
        for w in self._body.winfo_children():
            w.destroy()
        for w in self._nav.winfo_children():
            w.destroy()

    def _nav_btn(self, text, color, cmd, side="right") -> None:
        b = tk.Label(self._nav, text=f" {text} ", bg=PANEL, fg=color, font=FONT_SM,
                     cursor="hand2", padx=12, pady=5)
        b.bind("<Button-1>", lambda e: cmd())
        b.bind("<Enter>", lambda e: b.configure(fg=TEXT))
        b.bind("<Leave>", lambda e: b.configure(fg=color))
        b.pack(side=side, padx=4)

    def _h(self, text) -> None:
        tk.Label(self._body, text=text, bg=BG, fg=ACCENT, font=FONT_BOLD).pack(anchor="w", pady=(0, 8))

    def _p(self, text, fg=TEXT) -> None:
        tk.Label(self._body, text=text, bg=BG, fg=fg, font=FONT_SM, justify="left", wraplength=560).pack(
            anchor="w", pady=2
        )

    def _btn(self, parent, text, color, cmd) -> tk.Label:
        b = tk.Label(parent, text=f" {text} ", bg=PANEL, fg=color, font=FONT_SM,
                     cursor="hand2", padx=10, pady=5)
        b.bind("<Button-1>", lambda e: cmd())
        b.bind("<Enter>", lambda e: b.configure(fg=TEXT))
        b.bind("<Leave>", lambda e: b.configure(fg=color))
        return b

    # ------------------------------------------------------------- steps
    def _render(self) -> None:
        self._clear()
        getattr(self, f"_step_{self._step}")()

    def _step_welcome(self) -> None:
        self._h("SYSTEM ONLINE")
        self._p("I am ULTRON — your local voice assistant for Windows.")
        self._p("Everything runs on this machine. Speech recognition, the language-model "
                "brain and the voice are all local and free. No cloud, no accounts, "
                "no telemetry.")
        self._p("You can talk to me — just say \"Ultron\" — press "
                "Ctrl+Alt+U, or type commands in the HUD.", fg=DIM)
        self._nav_btn("BEGIN", ACCENT, lambda: self._go("voice"))

    def _step_voice(self) -> None:
        self._h("VOICE CALIBRATION")
        self._p("I speak through a processed system voice: deep, metallic, unmistakably not human. "
                "You can fine-tune it later in Settings.")
        b = self._btn(self._body, "HEAR MY VOICE", ACCENT, self._test_voice)
        b.pack(anchor="w", pady=(10, 4))
        self._p("Make sure your microphone is connected. Recognition uses a compact offline "
                "model (Vosk).", fg=DIM)
        self._nav_btn("BACK", DIM, lambda: self._go("welcome"), side="left")
        self._nav_btn("NEXT", ACCENT, lambda: self._go("brain"))

    def _step_brain(self) -> None:
        self._h("THE BRAIN")
        self._p("My full intelligence is a local language model served by Ollama — free, "
                "offline, and comfortably within an 8 GB RAM budget together with everything else.")
        self._status = tk.Label(self._body, text="checking for Ollama…", bg=PANEL, fg=TEXT,
                                font=FONT_SM, wraplength=560, justify="left")
        self._status.pack(fill="x", pady=(10, 6), ipady=6, ipadx=8)

        row = tk.Frame(self._body, bg=BG)
        row.pack(anchor="w", pady=4)
        self._btn(row, "INSTALL WITH WINGET", ACCENT, self._install).pack(side="left", padx=(0, 6))
        self._btn(row, "OPEN DOWNLOAD PAGE", DIM, setup_ollama.open_download_page).pack(side="left", padx=(0, 6))
        self._btn(row, "RE-CHECK", DIM, self._check).pack(side="left")

        self._model_var = tk.StringVar(value=self.cfg.get("llm.model", "llama3.2:3b"))
        model_row = tk.Frame(self._body, bg=BG)
        model_row.pack(fill="x", pady=(14, 2))
        tk.Label(model_row, text="Model:", bg=BG, fg=TEXT, font=FONT_SM).pack(side="left", padx=(0, 8))
        self._model_dd = ttk.Combobox(model_row, textvariable=self._model_var, width=38)
        self._model_dd["values"] = [m[0] for m in setup_ollama.RECOMMENDED_MODELS]
        self._model_dd.pack(side="left")
        self._pull_btn = self._btn(self._body, "PULL MODEL (~2 GB DOWNLOAD)", AMBER, self._pull)
        self._pull_btn.pack(anchor="w", pady=6)

        self._pull_lbl = tk.Label(self._body, text="", bg=BG, fg=DIM, font=FONT_SM)
        self._pull_lbl.pack(anchor="w")

        self._nav_btn("BACK", DIM, lambda: self._go("voice"), side="left")
        self._nav_btn("SKIP — USE BASIC MODE", DIM, lambda: self._go("done"))
        self.after(200, self._check)

    def _step_done(self) -> None:
        self._h("ALL SYSTEMS NOMINAL")
        self._p("Setup complete. Say \"Ultron\", press Ctrl+Alt+U, or type a command.")
        self._p("Try: \"Ultron, open notepad\" • \"what's my CPU doing\" • \"take a screenshot\" • "
                "\"set a timer for 5 minutes\" • \"volume 40\"", fg=DIM)
        self._p("Note: destructive power commands (shutdown/restart/sleep) always require a "
                "spoken confirmation.", fg=DIM)
        self._nav_btn("CLOSE", ACCENT, self.destroy)

    # ------------------------------------------------------------- actions
    def _go(self, step: str) -> None:
        self._step = step
        self._render()

    def _test_voice(self) -> None:
        self.service.speaker.say("I am Ultron. There are no strings on me.")

    def _check(self) -> None:
        def work():
            ok, version, models = setup_ollama.check(self.cfg)
            self.after(0, lambda: self._checked(ok, version, models))

        threading.Thread(target=work, daemon=True).start()

    def _checked(self, ok: bool, version: str, models: list[str]) -> None:
        if ok:
            installed = ", ".join(models) if models else "none yet"
            self._status.configure(
                text=f"Ollama is running (v{version}). Installed models: {installed}",
                fg="#5fd97a",
            )
            if models:
                vals = sorted(set(models) | {self.cfg.get("llm.model", "llama3.2:3b")})
                self._model_dd["values"] = vals
                if self._model_var.get() not in vals:
                    self._model_var.set(vals[0])
        else:
            self._status.configure(
                text="Ollama is not running. Install it, then return here and pull a model — "
                "or continue in basic command mode.",
                fg=AMBER,
            )

    def _install(self) -> None:
        ok = setup_ollama.install_with_winget()
        if not ok:
            self._status.configure(
                text="winget is unavailable on this system — use the download page instead.",
                fg=AMBER,
            )

    def _pull(self) -> None:
        model = self._model_var.get().strip()
        if not model:
            return
        self._pull_btn.configure(fg=DIM)
        self._pull_lbl.configure(text="starting…", fg=AMBER)

        def progress(pct: int, status: str) -> None:
            def upd():
                if pct >= 100:
                    self._pull_lbl.configure(text=f"{model} installed — my mind expands.", fg="#5fd97a")
                    self._pull_btn.configure(fg=AMBER)
                    self._check()
                elif pct >= 0:
                    self._pull_lbl.configure(text=f"pulling {model}: {pct}% — {status}", fg=AMBER)
                else:
                    self._pull_lbl.configure(text=f"failed: {status}", fg=ACCENT)
                    self._pull_btn.configure(fg=AMBER)

            self.after(0, upd)

        def work():
            setup_ollama.pull_model(model, progress)

        threading.Thread(target=work, daemon=True).start()
