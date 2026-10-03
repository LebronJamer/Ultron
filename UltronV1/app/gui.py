"""The ULTRON HUD: a frameless dark interface with an animated core,
live transcript, console log, and typed command input."""

from __future__ import annotations

import math
import time

import tkinter as tk
from tkinter import scrolledtext, ttk

from . import __version__
from .paths import resource

# ------------------------------------------------------------------ theme
BG = "#08080c"
PANEL = "#101018"
PANEL2 = "#16161f"
EDGE = "#26262f"
ACCENT = "#ff3b30"
ACCENT_DIM = "#7a1518"
AMBER = "#ff9f0a"
TEXT = "#e8e8ee"
DIM = "#8a8a96"

FONT = ("Segoe UI", 10)
FONT_SM = ("Segoe UI", 9)
FONT_BOLD = ("Segoe UI Semibold", 11)
FONT_TITLE = ("Segoe UI Semibold", 13)
FONT_MONO = ("Consolas", 10)

STATE_STYLE = {
    "standby": {"color": ACCENT_DIM, "speed": 10.0, "label": "STANDBY — say \"Ultron\""},
    "listening": {"color": ACCENT, "speed": 80.0, "label": "LISTENING"},
    "thinking": {"color": AMBER, "speed": 320.0, "label": "PROCESSING"},
    "speaking": {"color": ACCENT, "speed": 140.0, "label": "SPEAKING"},
}


def _enable_dpi_awareness() -> None:
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass


class UltronHUD(tk.Tk):
    def __init__(self, cfg, bus, service) -> None:
        super().__init__()
        self.cfg = cfg
        self.bus = bus
        self.service = service

        self._state = "standby"
        self._level = 0.0
        self._smooth_level = 0.0
        self._t0 = time.monotonic()
        self._angle = 0.0

        self.title("Ultron")
        self.overrideredirect(True)
        self.configure(bg=BG)
        self.minsize(760, 620)
        self._size_to_default()
        self._center()

        try:
            self.iconbitmap(str(resource("assets/icons/icon.ico")))
        except Exception:
            pass

        self._build_titlebar()
        self._build_body()
        self._bind_bus()

        self.protocol("WM_DELETE_WINDOW", self._quit)
        self.after(33, self._animate)
        self.after(60, self._pump)

    # ------------------------------------------------------------- layout
    def _size_to_default(self) -> None:
        try:
            sw = self.winfo_screenwidth()
            sh = self.winfo_screenheight()
        except Exception:
            sw, sh = 1920, 1080
        w, h = min(880, max(760, sw // 2)), min(720, max(620, sh * 2 // 3))
        self.geometry(f"{w}x{h}")

    def _center(self) -> None:
        self.update_idletasks()
        w, h = self.winfo_width(), self.winfo_height()
        x = (self.winfo_screenwidth() - w) // 2
        y = (self.winfo_screenheight() - h) // 3
        self.geometry(f"+{x}+{y}")

    def _build_titlebar(self) -> None:
        bar = tk.Frame(self, bg=PANEL, height=38)
        bar.pack(fill="x", side="top")
        bar.pack_propagate(False)

        logo = tk.Canvas(bar, width=26, height=26, bg=PANEL, highlightthickness=0)
        logo.pack(side="left", padx=(12, 6), pady=6)
        logo.create_oval(4, 4, 22, 22, outline=ACCENT, width=2)
        logo.create_oval(9, 9, 17, 17, fill=ACCENT, outline="")

        tk.Label(bar, text="ULTRON // V1", bg=PANEL, fg=TEXT, font=FONT_TITLE).pack(side="left")
        tk.Label(bar, text=f"  v{__version__}", bg=PANEL, fg=DIM, font=FONT_SM).pack(side="left")

        for text, cmd in (("\u2014", self._hide), ("\u2715", self._quit)):
            b = tk.Label(bar, text=f" {text} ", bg=PANEL, fg=DIM, font=FONT, cursor="hand2")
            b.pack(side="right", padx=2)
            b.bind("<Button-1>", lambda e, c=cmd: c())
            b.bind("<Enter>", lambda e, w=b: w.configure(fg=ACCENT))
            b.bind("<Leave>", lambda e, w=b: w.configure(fg=DIM))

        # window dragging
        for widget in (bar, logo):
            widget.bind("<Button-1>", self._drag_start)
            widget.bind("<B1-Motion>", self._drag_move)
        for child in bar.winfo_children():
            if isinstance(child, tk.Label) and child.cget("text").startswith("  v"):
                pass

        # allow dragging from any empty bar space
        bar.bind("<Button-1>", self._drag_start)
        bar.bind("<B1-Motion>", self._drag_move)

    def _drag_start(self, event) -> None:
        self._dx = event.x
        self._dy = event.y

    def _drag_move(self, event) -> None:
        x = self.winfo_x() + event.x - getattr(self, "_dx", 0)
        y = self.winfo_y() + event.y - getattr(self, "_dy", 0)
        self.geometry(f"+{x}+{y}")

    def _build_body(self) -> None:
        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True)

        # --- core canvas ------------------------------------------------
        self.canvas = tk.Canvas(body, width=320, height=320, bg=BG, highlightthickness=0)
        self.canvas.pack(pady=(24, 4))

        self._status_lbl = tk.Label(body, text=STATE_STYLE["standby"]["label"], bg=BG, fg=ACCENT, font=FONT_BOLD)
        self._status_lbl.pack(pady=(0, 2))
        self._partial_lbl = tk.Label(body, text="", bg=BG, fg=DIM, font=FONT_SM, wraplength=640, justify="center")
        self._partial_lbl.pack(pady=(0, 10), fill="x")

        # --- brain status -------------------------------------------------
        brain_bar = tk.Frame(body, bg=PANEL)
        brain_bar.pack(fill="x", padx=18, pady=(0, 8))
        self._brain_lbl = tk.Label(brain_bar, text="brain: checking…", bg=PANEL, fg=DIM, font=FONT_SM)
        self._brain_lbl.pack(side="left", padx=10, pady=5)
        self._brain_btn = tk.Label(
            brain_bar, text="set up brain", bg=PANEL, fg=ACCENT, font=FONT_SM, cursor="hand2"
        )
        self._brain_btn.pack(side="right", padx=10, pady=5)
        self._brain_btn.bind("<Button-1>", lambda e: self.open_wizard())
        self._brain_btn.bind("<Enter>", lambda e: self._brain_btn.configure(fg=TEXT))
        self._brain_btn.bind("<Leave>", lambda e: self._brain_btn.configure(fg=ACCENT))

        # --- console ------------------------------------------------------
        console_wrap = tk.Frame(body, bg=PANEL)
        console_wrap.pack(fill="both", expand=True, padx=18, pady=(0, 8))
        self.console = scrolledtext.ScrolledText(
            console_wrap,
            bg=PANEL2,
            fg=DIM,
            insertbackground=TEXT,
            font=FONT_MONO,
            relief="flat",
            state="disabled",
            wrap="word",
            height=8,
        )
        self.console.pack(fill="both", expand=True, padx=1, pady=1)
        for tag, color, bold in (
            ("user", "#ff8177", True),
            ("ultron", TEXT, True),
            ("system", DIM, False),
            ("error", AMBER, False),
        ):
            self.console.tag_configure(tag, foreground=color, font=(FONT_MONO[0], FONT_MONO[1], "bold") if bold else FONT_MONO)

        # --- input row ------------------------------------------------------
        input_row = tk.Frame(body, bg=BG)
        input_row.pack(fill="x", padx=18, pady=(0, 6))

        self._entry = tk.Entry(input_row, bg=PANEL2, fg=TEXT, insertbackground=ACCENT,
                               relief="flat", font=FONT, justify="left")
        self._entry.pack(side="left", fill="x", expand=True, ipady=7, padx=(0, 8))
        self._entry.insert(0, "")
        self._entry.bind("<Return>", self._send_text)
        self._entry.bind("<FocusIn>", lambda e: self._placeholder_clear())

        send = self._flat_btn(input_row, "SEND", ACCENT, self._send_text)
        send.pack(side="right", padx=(0, 8))

        self._mic_btn = self._flat_btn(input_row, "MIC ON", AMBER, self._toggle_mic)
        self._mic_btn.pack(side="right", padx=(0, 8))
        self._settings_btn = self._flat_btn(input_row, "SETTINGS", DIM, self.open_settings)
        self._settings_btn.pack(side="right")
        self._wizard_btn = self._flat_btn(input_row, "SETUP", DIM, self.open_wizard)
        self._wizard_btn.pack(side="right", padx=(0, 8))

    def _flat_btn(self, parent, text, color, cmd) -> tk.Label:
        b = tk.Label(parent, text=f" {text} ", bg=PANEL, fg=color, font=FONT_SM,
                     cursor="hand2", padx=8, pady=4)
        b.bind("<Button-1>", lambda e: cmd())
        b.bind("<Enter>", lambda e, w=b, c=color: w.configure(fg=TEXT))
        b.bind("<Leave>", lambda e, w=b, c=color: w.configure(fg=c))
        return b

    # --------------------------------------------------------------- bus
    def _bind_bus(self) -> None:
        self.bus.subscribe("state", self._on_state)
        self.bus.subscribe("partial", self._on_partial)
        self.bus.subscribe("user_said", self._on_user_said)
        self.bus.subscribe("reply", self._on_reply)
        self.bus.subscribe("llm_status", self._on_llm_status)
        self.bus.subscribe("mic_error", self._on_mic_error)
        self.bus.subscribe("muted", self._on_muted)
        self.bus.subscribe("download_progress", self._on_download)
        self.bus.subscribe("level", self._on_level)

    def _pump(self) -> None:
        self.bus.dispatch()
        self.after(60, self._pump)

    # ------------------------------------------------------------ events
    def _on_state(self, state: str) -> None:
        self._state = state
        style = STATE_STYLE.get(state, STATE_STYLE["standby"])
        self._status_lbl.configure(text=style["label"], fg=style["color"])

    def _on_partial(self, text: str) -> None:
        self._partial_lbl.configure(text=f'"{text}"')

    def _on_user_said(self, text: str) -> None:
        self._partial_lbl.configure(text="")
        self._log(f"you  > {text}", "user")

    def _on_reply(self, text: str) -> None:
        self._log(f"ultron > {text}", "ultron")

    def _on_llm_status(self, info: dict) -> None:
        if info.get("available"):
            self._brain_lbl.configure(
                text=f"brain: online — {info.get('model', '?')} (ollama {info.get('version', '?')})", fg="#5fd97a"
            )
            self._brain_btn.pack_forget()
        else:
            self._brain_lbl.configure(text="brain: offline — basic command mode (install Ollama for full intelligence)", fg=AMBER)
            self._brain_btn.pack(side="right", padx=10, pady=5)

    def _on_mic_error(self, msg: str) -> None:
        self._log(f"! mic: {msg}", "error")

    def _on_muted(self, muted: bool) -> None:
        self._mic_btn.configure(text="MIC OFF" if muted else "MIC ON")
        if muted:
            self._log("microphone muted", "system")

    def _on_download(self, info: dict) -> None:
        label = info.get("label", "")
        pct = info.get("pct", 0)
        self._log(f"download: {label} {pct}%", "system")

    def _log(self, text: str, tag: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        self.console.configure(state="normal")
        self.console.insert("end", f"[{stamp}] {text}\n", tag)
        self.console.see("end")
        self.console.configure(state="disabled")

    # ------------------------------------------------------------- actions
    def _send_text(self, event=None) -> None:
        text = self._entry.get().strip()
        if not text:
            return
        self._entry.delete(0, "end")
        self.service.submit_text(text)

    def _toggle_mic(self) -> None:
        self.service.set_muted(not self.service.muted)

    def open_settings(self) -> None:
        from .settings_ui import SettingsDialog

        SettingsDialog(self, self.cfg, self.bus, self.service)

    def open_wizard(self) -> None:
        from .wizard import FirstRunWizard

        FirstRunWizard(self, self.cfg, self.bus, self.service)

    # ------------------------------------------------------------ animation
    def _animate(self) -> None:
        style = STATE_STYLE.get(self._state, STATE_STYLE["standby"])
        color = style["color"]
        speed = style["speed"]
        self._angle = (self._angle + speed * 0.033) % 360
        t = time.monotonic() - self._t0

        # smooth mic level
        target = self._level if self._state == "listening" else 0.0
        self._smooth_level += (target - self._smooth_level) * 0.25

        c = self.canvas
        c.delete("all")
        cx, cy = 160, 160

        # pulse
        if self._state == "speaking":
            pulse = 1.0 + 0.10 * math.sin(2 * math.pi * 3.2 * t)
        elif self._state == "standby":
            pulse = 1.0 + 0.04 * math.sin(2 * math.pi * 0.5 * t)
        else:
            pulse = 1.0

        # rotating outer rings
        c.create_arc(cx - 140, cy - 140, cx + 140, cy + 140, start=self._angle,
                     extent=300, style="arc", outline=color, width=1)
        c.create_arc(cx - 122, cy - 122, cx + 122, cy + 122, start=-self._angle * 1.6,
                     extent=90, style="arc", outline=color, width=2)
        c.create_arc(cx - 104, cy - 104, cx + 104, cy + 104, start=self._angle * 2.2 + 120,
                     extent=40, style="arc", outline=color, width=1)

        # core
        r = (52 + 34 * self._smooth_level) * pulse
        glow_layers = 3
        for i in range(glow_layers, 0, -1):
            rr = r + i * 7
            shade = self._mix(color, "#000000", 0.55 + 0.15 * i)
            c.create_oval(cx - rr, cy - rr, cx + rr, cy + rr, fill=shade, outline="")

        c.create_oval(cx - r, cy - r, cx + r, cy + r, fill=color, outline="")

        # three 'mouth' slits — the Ultron signature
        for i, (dy, half) in enumerate(((14, 30), (26, 22), (36, 15))):
            shade = self._mix("#000000", color, 0.25)
            c.create_line(cx - half, cy + dy * pulse, cx + half, cy + dy * pulse,
                          fill=shade, width=3)

        # inner eye slit
        c.create_line(cx - 26, cy - 12, cx + 26, cy - 12, fill="#ffffff", width=2)

        self.after(33, self._animate)

    @staticmethod
    def _mix(c1: str, c2: str, ratio: float) -> str:
        """Blend two hex colors; ratio = weight of c2."""
        r1, g1, b1 = int(c1[1:3], 16), int(c1[3:5], 16), int(c1[5:7], 16)
        r2, g2, b2 = int(c2[1:3], 16), int(c2[3:5], 16), int(c2[5:7], 16)
        r = int(r1 + (r2 - r1) * ratio)
        g = int(g1 + (g2 - g1) * ratio)
        b = int(b1 + (b2 - b1) * ratio)
        return f"#{r:02x}{g:02x}{b:02x}"

    # --------------------------------------------------------------- misc
    def _hide(self) -> None:
        self.withdraw()

    def show(self) -> None:
        self.deiconify()
        self._center()

    def _quit(self) -> None:
        if hasattr(self, "_on_quit_cb") and self._on_quit_cb:
            self._on_quit_cb()
        self.destroy()

    def on_quit(self, cb) -> None:
        self._on_quit_cb = cb
