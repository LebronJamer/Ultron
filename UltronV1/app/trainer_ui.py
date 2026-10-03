"""Voice Training Studio: wake-word training, custom command teaching,
microphone selection and recognition model choice.

Why "training" works: the recognizer is a static acoustic model, so instead
of adapting the model we adapt the *matching*:

* you say the wake word several times; we record exactly what the engine
  hears on your microphone (variants like "altron", "ultra on"), and those
  variants become the constrained wake grammar — the standby decoder can
  then ONLY produce those phrases, which eliminates most missed wake-ups
  and false triggers;
* custom commands map your phrases (with all their learned variants) to
  actions, matched fuzzily before the LLM ever runs — instant and offline.
"""

from __future__ import annotations

import threading
import tkinter as tk
from tkinter import ttk

from . import modelfetch
from .custom_commands import match_custom_command, new_command_id, normalize, parse_params_block, score
from .commands.executor import action_catalog
from .gui import ACCENT, AMBER, BG, DIM, FONT, FONT_BOLD, FONT_SM, PANEL, PANEL2, TEXT
from .paths import resource
from .stt import list_input_devices

GREEN = "#5fd97a"
RED = "#ff6b6b"

WAKE_SAMPLES = 5


class TrainingStudio(tk.Toplevel):
    def __init__(self, master, cfg, bus, service) -> None:
        super().__init__(master)
        self.cfg = cfg
        self.bus = bus
        self.service = service

        self._session = None           # {"type": "wake"|"phrase"|"waketest"|"matchtest", "remaining": int}
        self._session_job = None       # after() id for auto-stop
        self._commands: list[dict] = [dict(c) for c in (cfg.get("custom_commands", []) or [])]
        self._edit_id: str | None = None

        self.title("Ultron — Voice Training Studio")
        self.configure(bg=BG)
        self.geometry("720x640")
        self.minsize(680, 600)
        self.transient(master)
        self.grab_set()
        try:
            self.iconbitmap(str(resource("assets/icons/icon.ico")))
        except Exception:
            pass

        container = tk.Frame(self, bg=BG)
        container.pack(fill="both", expand=True, padx=16, pady=12)
        tk.Label(container, text="VOICE TRAINING STUDIO", bg=BG, fg=ACCENT, font=FONT_BOLD).pack(anchor="w")

        nb = ttk.Notebook(container)
        nb.pack(fill="both", expand=True, pady=(8, 6))
        self.notebook = nb
        self._build_wake_tab(nb)
        self._build_commands_tab(nb)
        self._build_mic_tab(nb)

        hint = tk.Label(
            container,
            text="Speak 10–30 cm from the mic. Train in the room you normally use — background noise changes what I hear.",
            bg=BG, fg=DIM, font=FONT_SM, wraplength=640, justify="left",
        )
        hint.pack(fill="x", pady=(4, 0))

        self.protocol("WM_DELETE_WINDOW", self._close)

        # bus wiring
        self.bus.subscribe("train_final", self._on_train_final)
        self.bus.subscribe("train_partial", self._on_train_partial)
        self.bus.subscribe("level", self._on_level)
        self.bus.subscribe("download_progress", self._on_dl_progress)

    # ================================================================ tabs
    def _build_wake_tab(self, nb) -> None:
        f = tk.Frame(nb, bg=BG)
        nb.add(f, text=" Wake word ")

        row = tk.Frame(f, bg=BG)
        row.pack(fill="x", padx=12, pady=(12, 4))
        tk.Label(row, text="Wake word:", bg=BG, fg=TEXT, font=FONT_SM).pack(side="left")
        self._wake_var = tk.StringVar(value=self.cfg.get("wake_word", "ultron"))
        e = tk.Entry(row, textvariable=self._wake_var, bg=PANEL2, fg=TEXT,
                     insertbackground=ACCENT, relief="flat", font=FONT, width=16)
        e.pack(side="left", padx=8)

        self._btn(row, "RECORD 5 SAMPLES", ACCENT, lambda: self._start_wake_session()).pack(side="left", padx=4)
        self._wake_test_btn = self._btn(row, "TEST DETECTION", AMBER, self._toggle_wake_test)
        self._wake_test_btn.pack(side="left", padx=4)
        self._btn(row, "SAVE", GREEN, self._save_wake).pack(side="right", padx=4)

        self._wake_status = tk.Label(f, text="Press RECORD, then say the wake word five times.",
                                     bg=BG, fg=DIM, font=FONT_SM, anchor="w", wraplength=640, justify="left")
        self._wake_status.pack(fill="x", padx=12)

        # live level meter
        lvl = tk.Frame(f, bg=BG)
        lvl.pack(fill="x", padx=12, pady=(6, 0))
        tk.Label(lvl, text="live level:", bg=BG, fg=DIM, font=FONT_SM).pack(side="left")
        self._level_canvas = tk.Canvas(lvl, width=340, height=12, bg=PANEL2, highlightthickness=0)
        self._level_canvas.pack(side="left", padx=8)

        mid = tk.Frame(f, bg=BG)
        mid.pack(fill="both", expand=True, padx=12, pady=8)

        left = tk.Frame(mid, bg=BG)
        left.pack(side="left", fill="both", expand=True)
        tk.Label(left, text="Heard during training", bg=BG, fg=TEXT, font=FONT_SM).pack(anchor="w")
        self._samples_box = tk.Listbox(left, bg=PANEL, fg=TEXT, relief="flat", font=FONT_SM,
                                       height=8, selectbackground=ACCENT_DIM_SEL)
        self._samples_box.pack(fill="both", expand=True, pady=(2, 0))

        right = tk.Frame(mid, bg=BG)
        right.pack(side="left", fill="both", expand=True, padx=(10, 0))
        tk.Label(right, text="Wake-word variants (one per line — keep the ones you want)",
                 bg=BG, fg=TEXT, font=FONT_SM).pack(anchor="w")
        self._variants_txt = tk.Text(right, bg=PANEL, fg=TEXT, relief="flat", font=FONT_SM,
                                     height=8, insertbackground=ACCENT, wrap="word")
        self._variants_txt.pack(fill="both", expand=True, pady=(2, 0))
        existing = self.cfg.get("wake.variants", []) or []
        if existing:
            self._variants_txt.insert("1.0", "\n".join(existing))

        tip = tk.Label(
            f,
            text="Variants are what the engine actually hears (e.g. \"altron\", \"ultra on\"). "
                 "They are used both for fuzzy matching and as a constrained grammar so background "
                 "speech can't produce them by accident. SAVE applies them immediately.",
            bg=BG, fg=DIM, font=FONT_SM, wraplength=640, justify="left",
        )
        tip.pack(fill="x", padx=12, pady=(0, 8))

    def _build_commands_tab(self, nb) -> None:
        f = tk.Frame(nb, bg=BG)
        nb.add(f, text=" Custom commands ")

        top = tk.Frame(f, bg=BG)
        top.pack(fill="both", expand=True, padx=12, pady=(12, 0))

        # ---- left: list ----
        left = tk.Frame(top, bg=BG)
        left.pack(side="left", fill="y")
        tk.Label(left, text="Commands", bg=BG, fg=TEXT, font=FONT_SM).pack(anchor="w")
        self._cmd_box = tk.Listbox(left, bg=PANEL, fg=TEXT, relief="flat", font=FONT_SM,
                                   width=26, height=14, selectbackground=ACCENT_DIM_SEL)
        self._cmd_box.pack(fill="y", expand=True, pady=(2, 4))
        self._cmd_box.bind("<<ListboxSelect>>", self._load_selected_command)
        row = tk.Frame(left, bg=BG)
        row.pack(fill="x")
        self._btn(row, "NEW", ACCENT, self._new_command).pack(side="left", padx=(0, 4))
        self._btn(row, "DELETE", RED, self._delete_command).pack(side="left")

        # ---- right: editor ----
        right = tk.Frame(top, bg=BG)
        right.pack(side="left", fill="both", expand=True, padx=(10, 0))

        self._cc_name = tk.StringVar()
        self._row_entry(right, "Name:", self._cc_name)

        self._cc_reply = tk.StringVar()
        self._cc_action_label = tk.StringVar(value="open_app — Open application")
        catalog = action_catalog()
        self._action_labels = {f"{a} — {label}": a for a, label, _params in catalog}
        self._label_action = {a: f"{a} — {label}" for a, label, _params in catalog}
        self._action_params = {a: params for a, label, params in catalog}
        tk.Label(right, text="Action:", bg=BG, fg=TEXT, font=FONT_SM).pack(anchor="w")
        dd = ttk.Combobox(right, textvariable=self._cc_action_label,
                          values=list(self._action_labels.keys()), state="readonly")
        dd.pack(anchor="w", fill="x")
        dd.bind("<<ComboboxSelected>>", lambda e: self._update_param_hint())

        self._param_hint = tk.Label(right, text="", bg=BG, fg=DIM, font=FONT_SM)
        self._param_hint.pack(anchor="w")

        tk.Label(right, text="Params (one per line:  key = value):", bg=BG, fg=TEXT, font=FONT_SM).pack(anchor="w")
        self._params_txt = tk.Text(right, bg=PANEL, fg=TEXT, relief="flat", font=FONT_SM,
                                   height=3, insertbackground=ACCENT)
        self._params_txt.pack(fill="x", pady=(2, 6))

        self._row_entry(right, "Custom reply (optional):", self._cc_reply, wide=True)
        self._cc_enabled = tk.BooleanVar(value=True)
        tk.Checkbutton(right, text="Enabled", variable=self._cc_enabled, bg=BG, fg=TEXT,
                       font=FONT_SM, selectcolor=PANEL2, activebackground=BG,
                       activeforeground=ACCENT, highlightthickness=0).pack(anchor="w")

        tk.Label(right, text="Trigger phrases:", bg=BG, fg=TEXT, font=FONT_SM).pack(anchor="w", pady=(6, 0))
        prow = tk.Frame(right, bg=BG)
        prow.pack(fill="x")
        self._phrase_box = tk.Listbox(prow, bg=PANEL, fg=TEXT, relief="flat", font=FONT_SM,
                                      height=4, selectbackground=ACCENT_DIM_SEL)
        self._phrase_box.pack(side="left", fill="both", expand=True)
        pbtns = tk.Frame(prow, bg=BG)
        pbtns.pack(side="left", padx=(6, 0))
        self._btn(pbtns, "RECORD PHRASE", ACCENT, self._record_phrase).pack(anchor="w", pady=1)
        self._btn(pbtns, "ADD HEARD", GREEN, self._add_heard_phrase).pack(anchor="w", pady=1)
        self._btn(pbtns, "REMOVE", RED, self._remove_phrase).pack(anchor="w", pady=1)

        self._last_heard = tk.StringVar(value="(nothing recorded yet)")
        heard_row = tk.Frame(right, bg=BG)
        heard_row.pack(fill="x", pady=(4, 0))
        tk.Label(heard_row, text="Last heard:", bg=BG, fg=DIM, font=FONT_SM).pack(side="left")
        tk.Label(heard_row, textvariable=self._last_heard, bg=BG, fg=AMBER, font=FONT_SM).pack(side="left", padx=6)

        # ---- bottom bar ----
        bar = tk.Frame(f, bg=BG)
        bar.pack(fill="x", padx=12, pady=8)
        self._btn(bar, "SAVE COMMAND", GREEN, self._save_command).pack(side="right", padx=4)
        self._btn(bar, "TEST MATCH", AMBER, self._start_match_test).pack(side="right", padx=4)
        self._cc_status = tk.Label(bar, text="", bg=BG, fg=DIM, font=FONT_SM, anchor="w")
        self._cc_status.pack(side="left", fill="x", expand=True)

        self._refresh_command_list()

    def _build_mic_tab(self, nb) -> None:
        f = tk.Frame(nb, bg=BG)
        nb.add(f, text=" Microphone & Model ")

        # ---- microphone ----
        tk.Label(f, text="Microphone", bg=BG, fg=ACCENT, font=FONT_BOLD).pack(anchor="w", padx=12, pady=(12, 2))
        row = tk.Frame(f, bg=BG)
        row.pack(fill="x", padx=12, pady=4)
        self._mic_var = tk.StringVar(value="")
        self._mic_dd = ttk.Combobox(row, textvariable=self._mic_var, state="readonly", width=52)
        self._mic_dd.pack(side="left", padx=(0, 8))
        self._btn(row, "REFRESH", DIM, self._refresh_mics).pack(side="left", padx=4)
        self._btn(row, "APPLY", ACCENT, self._apply_mic).pack(side="left", padx=4)
        self._mic_status = tk.Label(
            f, text="If detection is poor, make sure the right device is selected — webcams and "
                    "monitor mics are usually much worse than headsets.",
            bg=BG, fg=DIM, font=FONT_SM, wraplength=640, justify="left")
        self._mic_status.pack(fill="x", padx=12)

        # ---- model ----
        tk.Label(f, text="Recognition model", bg=BG, fg=ACCENT, font=FONT_BOLD).pack(anchor="w", padx=12, pady=(14, 2))
        row = tk.Frame(f, bg=BG)
        row.pack(fill="x", padx=12, pady=4)
        self._model_var = tk.StringVar(value=modelfetch.active_key(self.cfg))
        self._model_dd = ttk.Combobox(
            row, textvariable=self._model_var, state="readonly", width=52,
            values=[f"{k} — {v['label']}" for k, v in modelfetch.MODEL_CATALOG.items()],
        )
        self._model_dd.pack(side="left", padx=(0, 8))
        self._btn(row, "APPLY MODEL", ACCENT, self._apply_model).pack(side="left", padx=4)
        self._btn(row, "DOWNLOAD", AMBER, self._download_model).pack(side="left", padx=4)

        self._model_status = tk.Label(f, text="", bg=BG, fg=DIM, font=FONT_SM,
                                      wraplength=640, justify="left")
        self._model_status.pack(fill="x", padx=12, pady=(2, 0))
        self._refresh_model_status()

        tip = tk.Label(
            f,
            text="The Large model (1.3 GB, free, offline) noticeably improves recognition — especially on "
                 "accents and in noisy rooms. It uses ~1 GB RAM, still within the 8 GB budget alongside the "
                 "llama3.2:3b brain. Download first, then APPLY MODEL.",
            bg=BG, fg=DIM, font=FONT_SM, wraplength=640, justify="left")
        tip.pack(fill="x", padx=12, pady=(8, 0))

        self._refresh_mics()

    # ============================================================ widgets
    def _btn(self, parent, text, color, cmd) -> tk.Label:
        b = tk.Label(parent, text=f" {text} ", bg=PANEL, fg=color, font=FONT_SM,
                     cursor="hand2", padx=8, pady=4)
        b.bind("<Button-1>", lambda e: cmd())
        b.bind("<Enter>", lambda e: b.configure(fg=TEXT))
        b.bind("<Leave>", lambda e: b.configure(fg=color))
        return b

    def _row_entry(self, parent, label, var, wide=False) -> None:
        row = tk.Frame(parent, bg=BG)
        row.pack(fill="x", pady=2)
        tk.Label(row, text=label, bg=BG, fg=TEXT, font=FONT_SM, width=24, anchor="w").pack(side="left")
        e = tk.Entry(row, textvariable=var, bg=PANEL2, fg=TEXT, insertbackground=ACCENT,
                     relief="flat", font=FONT)
        e.pack(side="left", fill="x", expand=True)

    # =========================================================== sessions
    def _start_session(self, kind: str, status: str, count: int = 1, timeout_s: float | None = None) -> bool:
        if self._session:
            self._stop_session()
        if not self.service.begin_training():
            self._wake_status.configure(
                text="Microphone unavailable. Check the Microphone & Model tab (model downloaded? device present?).",
                fg=RED,
            )
            return False
        self._session = {"type": kind, "remaining": count}
        self._wake_status.configure(text=status, fg=AMBER)
        if timeout_s:
            self._session_job = self.after(int(timeout_s * 1000), self._stop_session)
        return True

    def _stop_session(self) -> None:
        if self._session_job:
            try:
                self.after_cancel(self._session_job)
            except Exception:
                pass
            self._session_job = None
        was = self._session["type"] if self._session else None
        self._session = None
        self.service.end_training()
        if was == "waketest":
            self._wake_test_btn.configure(text="TEST DETECTION")
            self._wake_status.configure(text="Detection test stopped.", fg=DIM)
        elif was:
            self._wake_status.configure(text="Listening stopped.", fg=DIM)

    def _start_wake_session(self) -> None:
        word = self._wake_var.get().strip().lower()
        if not word:
            self._wake_status.configure(text="Enter a wake word first.", fg=RED)
            return
        self._samples_box.delete(0, "end")
        self._matched_variants: set[str] = set()
        ok = self._start_session(
            "wake", f"Say “{word}”… (sample 1 of {WAKE_SAMPLES})", count=WAKE_SAMPLES, timeout_s=60
        )
        if ok:
            self._wake_word_target = word

    def _toggle_wake_test(self) -> None:
        if self._session and self._session["type"] == "waketest":
            self._stop_session()
            return
        if self._start_session("waketest", "Say the wake word… (listening for 20 s)", timeout_s=20):
            self._wake_test_btn.configure(text="STOP TEST")

    def _record_phrase(self) -> None:
        self._start_session("phrase", "Say the trigger phrase once…", timeout_s=20)

    def _start_match_test(self) -> None:
        self._start_session("matchtest", "Say a trained phrase… (tests saved commands)", timeout_s=20)

    # ======================================================== bus handlers
    def _on_train_partial(self, text: str) -> None:
        if self._session:
            self._wake_status.configure(text=f'… "{text}"', fg=DIM)

    def _on_train_final(self, text: str) -> None:
        s = self._session
        if not s:
            return
        kind = s["type"]

        if kind == "wake":
            matched = self.service.matches_wake(text)
            norm = normalize(text)
            mark = "✓" if matched else "✗"
            self._samples_box.insert("end", f"{mark}  {text}")
            self._samples_box.see("end")
            if matched and norm and norm not in self._matched_variants:
                self._matched_variants.add(norm)
                current = self._variants_txt.get("1.0", "end").strip()
                lines = [l for l in current.splitlines() if l.strip()]
                if norm not in lines:
                    lines.append(norm)
                    self._variants_txt.delete("1.0", "end")
                    self._variants_txt.insert("1.0", "\n".join(lines))
            s["remaining"] -= 1
            if s["remaining"] <= 0:
                self._stop_session()
                n = len(self._matched_variants)
                self._wake_status.configure(
                    text=f"Training done — {n} variant(s) learned. Review the list and press SAVE.",
                    fg=GREEN if n else AMBER,
                )
            else:
                self._wake_status.configure(
                    text=f'Say "{self._wake_word_target}"… (sample {WAKE_SAMPLES - s["remaining"] + 1} of {WAKE_SAMPLES})',
                    fg=AMBER,
                )

        elif kind == "phrase":
            self._last_heard.set(text)
            self._wake_status.configure(text=f'Heard: "{text}" — press ADD HEARD to keep it as a variant.', fg=GREEN)
            self._stop_session()

        elif kind == "waketest":
            ok = self.service.matches_wake(text)
            self._wake_status.configure(
                text=f'heard "{text}" → {"WAKE MATCHED ✓" if ok else "no match ✗"}',
                fg=GREEN if ok else RED,
            )

        elif kind == "matchtest":
            m = match_custom_command(text, self.cfg.get("custom_commands", []) or [])
            if m:
                cc, phrase, sc = m
                self._cc_status.configure(
                    text=f'matched "{cc.get("name", "")}" (phrase: "{phrase}", {sc:.0%})', fg=GREEN
                )
            else:
                self._cc_status.configure(text=f'heard "{text}" — no saved command matched (save first?)', fg=RED)
            self._stop_session()

    def _on_level(self, level: float) -> None:
        c = self._level_canvas
        c.delete("all")
        w = int(c.winfo_width()) or 340
        fill = int(w * max(0.0, min(1.0, float(level))))
        color = GREEN if level > 0.12 else ACCENT
        if fill > 0:
            c.create_rectangle(0, 0, fill, 12, fill=color, outline="")

    def _on_dl_progress(self, info: dict) -> None:
        pct = info.get("pct", 0)
        status = info.get("label", "")
        if pct >= 100:
            self._model_status.configure(text=f"{status} — done. Press APPLY MODEL to activate.", fg=GREEN)
            self._refresh_model_status()
        elif pct >= 0:
            self._model_status.configure(text=f"downloading: {pct}% ({status})", fg=AMBER)
        else:
            self._model_status.configure(text=f"download failed: {status}", fg=RED)

    # ============================================================= actions
    def _save_wake(self) -> None:
        word = self._wake_var.get().strip().lower()
        if not word:
            self._wake_status.configure(text="Enter a wake word first.", fg=RED)
            return
        variants = []
        seen = set()
        for line in self._variants_txt.get("1.0", "end").splitlines():
            v = normalize(line)
            if v and len(v) >= 3 and v not in seen and v != word:
                seen.add(v)
                variants.append(v)
        self.cfg.set("wake_word", word)
        self.cfg.set("wake.variants", variants)
        self.cfg.save()
        self.service.apply_wake_settings()
        self._wake_status.configure(
            text=f"Saved — wake word “{word}” with {len(variants)} trained variant(s). Engine rebuilt.",
            fg=GREEN,
        )

    # ---- custom commands ----
    def _refresh_command_list(self) -> None:
        self._cmd_box.delete(0, "end")
        for cc in self._commands:
            mark = "" if cc.get("enabled", True) else "  (disabled)"
            self._cmd_box.insert("end", f"{cc.get('name', '?')}{mark}")

    def _load_selected_command(self, event=None) -> None:
        sel = self._cmd_box.curselection()
        if not sel:
            return
        cc = self._commands[sel[0]]
        self._edit_id = cc.get("id")
        self._cc_name.set(cc.get("name", ""))
        action = str(cc.get("action", "open_app"))
        self._cc_action_label.set(self._label_action.get(action, action))
        self._params_txt.delete("1.0", "end")
        params = cc.get("params") or {}
        self._params_txt.insert("1.0", "\n".join(f"{k} = {v}" for k, v in params.items()))
        self._cc_reply.set(cc.get("reply", "") or "")
        self._cc_enabled.set(bool(cc.get("enabled", True)))
        self._phrase_box.delete(0, "end")
        for p in cc.get("phrases", []) or []:
            self._phrase_box.insert("end", str(p))
        self._update_param_hint()

    def _new_command(self) -> None:
        self._edit_id = None
        self._cc_name.set("")
        self._cc_action_label.set("open_app — Open application")
        self._params_txt.delete("1.0", "end")
        self._params_txt.insert("1.0", "name = notepad")
        self._cc_reply.set("")
        self._cc_enabled.set(True)
        self._phrase_box.delete(0, "end")
        self._last_heard.set("(nothing recorded yet)")
        self._update_param_hint()
        self._cc_status.configure(text="New command — record or type trigger phrases, then SAVE COMMAND.", fg=DIM)

    def _delete_command(self) -> None:
        sel = self._cmd_box.curselection()
        if not sel:
            self._cc_status.configure(text="Select a command to delete.", fg=RED)
            return
        del self._commands[sel[0]]
        self._persist_commands()
        self._refresh_command_list()
        self._new_command()
        self._cc_status.configure(text="Command deleted.", fg=DIM)

    def _add_heard_phrase(self) -> None:
        text = self._last_heard.get().strip()
        if not text or text.startswith("(nothing"):
            self._cc_status.configure(text="Record a phrase first (RECORD PHRASE).", fg=RED)
            return
        self._phrase_box.insert("end", normalize(text))
        self._cc_status.configure(text=f'Added "{normalize(text)}" — record more variants or SAVE COMMAND.', fg=GREEN)

    def _remove_phrase(self) -> None:
        sel = self._phrase_box.curselection()
        if sel:
            self._phrase_box.delete(sel[0])

    def _update_param_hint(self) -> None:
        label = self._cc_action_label.get()
        action = self._action_labels.get(label, "none")
        params = self._action_params.get(action, [])
        self._param_hint.configure(text=f"params: {', '.join(params)}" if params else "params: none")

    def _save_command(self) -> None:
        label = self._cc_action_label.get()
        action = self._action_labels.get(label, "")
        name = self._cc_name.get().strip()
        phrases = [normalize(self._phrase_box.get(i)) for i in range(self._phrase_box.size())]
        phrases = [p for p in phrases if p]
        if not name:
            self._cc_status.configure(text="Give the command a name.", fg=RED)
            return
        if not action:
            self._cc_status.configure(text="Pick an action.", fg=RED)
            return
        if not phrases:
            self._cc_status.configure(text="Add at least one trigger phrase (record or type).", fg=RED)
            return
        cc = {
            "id": self._edit_id or new_command_id(),
            "name": name,
            "phrases": phrases,
            "action": action,
            "params": parse_params_block(self._params_txt.get("1.0", "end")),
            "reply": self._cc_reply.get().strip(),
            "enabled": bool(self._cc_enabled.get()),
        }
        if self._edit_id:
            for i, existing in enumerate(self._commands):
                if existing.get("id") == self._edit_id:
                    self._commands[i] = cc
                    break
            else:
                self._commands.append(cc)
        else:
            self._commands.append(cc)
            self._edit_id = cc["id"]
        self._persist_commands()
        self._refresh_command_list()
        self._cc_status.configure(
            text=f'Saved “{name}” — say any of its phrases after the wake word. Live immediately.', fg=GREEN
        )

    def _persist_commands(self) -> None:
        self.cfg.set("custom_commands", self._commands)
        self.cfg.save()

    # ---- mic & model ----
    def _refresh_mics(self) -> None:
        self._devices = list_input_devices()
        names = [f"{i}: {name}" for i, name in self._devices]
        self._mic_dd["values"] = names
        current = self.cfg.get("stt.device", None)
        if current is not None and any(i == current for i, _ in self._devices):
            idx = [i for i, _ in self._devices].index(current)
            self._mic_var.set(names[idx])
        elif names:
            self._mic_var.set(names[0])

    def _apply_mic(self) -> None:
        sel = self._mic_var.get()
        device = None
        if sel:
            try:
                device = int(sel.split(":", 1)[0])
            except ValueError:
                device = None
        self.service.set_mic(device)
        self._mic_status.configure(text=f"Microphone set to {sel or 'system default'}. Engine restarted.", fg=GREEN)

    def _selected_model_key(self) -> str:
        sel = self._model_var.get()
        return sel.split(" —", 1)[0].strip() if sel else "small"

    def _refresh_model_status(self) -> None:
        lines = []
        for key, info in modelfetch.MODEL_CATALOG.items():
            present = modelfetch.have_model(key)
            lines.append(f"{key}: {'installed' if present else 'not downloaded'} ({info['label']})")
        active = modelfetch.active_key(self.cfg)
        self._model_status.configure(
            text=f"Active: {active}. " + " | ".join(lines), fg=DIM
        )

    def _download_model(self) -> None:
        key = self._selected_model_key()

        def progress(pct, status):
            self.bus.emit("download_progress", {"label": status, "pct": pct})

        def work():
            ok = modelfetch.download(progress, key, self.cfg)
            if not ok:
                self.bus.emit("download_progress", {"label": "check your connection", "pct": -1})

        threading.Thread(target=work, daemon=True).start()
        self._model_status.configure(text=f"downloading {key} model…", fg=AMBER)

    def _apply_model(self) -> None:
        key = self._selected_model_key()
        if not modelfetch.have_model(key):
            self._model_status.configure(
                text=f"The {key} model is not downloaded yet — press DOWNLOAD first.", fg=RED
            )
            return
        self.service.set_stt_model(key)
        self._model_status.configure(text=f"Recognition model switched to {key}. Engine restarted.", fg=GREEN)
        self._refresh_model_status()

    # ================================================================ close
    def _close(self) -> None:
        if self._session:
            self._stop_session()
        else:
            self.service.end_training()
        for name, fn in (
            ("train_final", self._on_train_final),
            ("train_partial", self._on_train_partial),
            ("level", self._on_level),
            ("download_progress", self._on_dl_progress),
        ):
            self.bus.unsubscribe(name, fn)
        self.destroy()


ACCENT_DIM_SEL = "#4a1518"  # selection color for listboxes
