"""GUI smoke test: instantiates the real HUD and dialogs (no mainloop),
drives the tk event loop, and dispatches every bus event through the real
subscribers. Catches wiring bugs (missing handlers, bad attribute refs)
that static checks can miss.

Exits 0 with a warning if the environment has no display (e.g. headless
Linux); any other failure is a real bug and fails the build.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> int:
    try:
        import tkinter as tk
    except Exception as exc:  # no tkinter / no _tkinter build
        print(f"WARN: tkinter unavailable in this environment ({exc}); skipping GUI smoke")
        return 0

    from app.bus import EventBus
    from app.config import Config
    from app.gui import UltronHUD, _enable_dpi_awareness
    from app.service import AssistantService

    _enable_dpi_awareness()
    cfg = Config()
    bus = EventBus()
    svc = AssistantService(cfg, bus)

    try:
        hud = UltronHUD(cfg, bus, svc)
    except tk.TclError as exc:
        if "display" in str(exc).lower() or "window" in str(exc).lower():
            print(f"WARN: no display available ({exc}); skipping GUI smoke")
            return 0
        raise

    def pump(seconds: float) -> None:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            bus.dispatch()
            hud.update()
            time.sleep(0.02)

    # let _animate / _pump run a few cycles
    pump(0.6)

    # push every kind of bus event through the real subscribers
    bus.emit("state", "listening")
    bus.emit("level", 0.7)
    bus.emit("partial", "hello there")
    bus.emit("user_said", "open notepad")
    bus.emit("reply", "As you wish.")
    bus.emit("llm_status", {"available": False, "model": "llama3.2:3b", "models": [], "version": ""})
    bus.emit("llm_status", {"available": True, "model": "llama3.2:3b", "models": ["llama3.2:3b"], "version": "0.5"})
    bus.emit("mic_error", "simulated mic problem")
    bus.emit("muted", True)
    bus.emit("muted", False)
    bus.emit("download_progress", {"label": "speech model", "pct": 42})
    bus.emit("state", "standby")
    pump(0.6)

    # typed input path (entry -> service queue) without starting audio threads
    hud._entry.insert(0, "what time is it")
    hud._send_text()
    pump(0.4)

    # settings dialog
    from app.settings_ui import SettingsDialog

    d = SettingsDialog(hud, cfg, bus, svc)
    for _ in range(10):
        d.update()
        time.sleep(0.02)
    d.destroy()

    # first-run wizard: visit every step
    from app.wizard import FirstRunWizard

    w = FirstRunWizard(hud, cfg, bus, svc)
    for _ in range(10):
        w.update()
        time.sleep(0.02)
    for step in ("voice", "brain", "done"):
        w._go(step)
        pump(0.35)  # let the brain-check after() callback fire
    w.destroy()

    # voice training studio: render, switch tabs, simulate a training session
    from app.trainer_ui import TrainingStudio

    t = TrainingStudio(hud, cfg, bus, svc)
    for tab in (0, 1, 2):
        t.notebook.select(tab)
        pump(0.25)

    # simulate the bus traffic a real training session produces
    t._new_command()
    t._last_heard.set("open my workspace")
    t._add_heard_phrase()
    t._cc_name.set("smoke-command")
    t._cc_reply.set("smoke reply")
    t._save_command()
    bus.emit("train_partial", "ultr")
    bus.emit("train_final", "ultron")
    bus.emit("level", 0.55)
    bus.emit("download_progress", {"label": "model", "pct": 10})
    pump(0.4)

    # wake-word save path (writes config + rebuilds engine)
    t._wake_var.set("ultron")
    t._variants_txt.delete("1.0", "end")
    t._variants_txt.insert("1.0", "altron")
    t._save_wake()
    pump(0.3)

    # custom command end-to-end through the service (typed input)
    svc.submit_text("open my workspace")
    pump(1.0)

    t._close()
    pump(0.2)
    hud.destroy()
    print("gui smoke OK — HUD, settings, wizard and training studio all exercised")
    return 0


if __name__ == "__main__":
    sys.exit(main())
