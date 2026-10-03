"""Application entry point: wiring, single-instance guard, lifecycle."""

from __future__ import annotations

import argparse
import socket
import sys


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="Ultron", description="ULTRON voice assistant")
    parser.add_argument("--debug", action="store_true", help="verbose logging")
    parser.add_argument("--minimized", action="store_true", help="start hidden in the tray")
    parser.add_argument("--no-tray", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--settings", action="store_true", help="open settings on launch")
    args = parser.parse_args(argv)

    from . import __version__, log

    log.setup(debug=args.debug)
    lg = log.get()
    lg.info("Ultron v%s starting", __version__)

    # ---- single instance -------------------------------------------------
    lock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        lock.bind(("127.0.0.1", 52119))
        lock.listen(1)
    except OSError:
        print("Ultron is already running.")
        return 0

    from .bus import EventBus
    from .config import Config
    from .service import AssistantService

    cfg = Config()
    first_run = cfg.get("_first_run", True)
    cfg.set("_first_run", False)
    cfg.save()

    bus = EventBus()
    service = AssistantService(cfg, bus)

    # ---- GUI ---------------------------------------------------------------
    try:
        from .gui import UltronHUD, _enable_dpi_awareness
    except Exception:
        lg.exception("GUI unavailable (tkinter missing?)")
        return 1

    _enable_dpi_awareness()
    hud = UltronHUD(cfg, bus, service)

    # ---- tray ---------------------------------------------------------------
    tray_icon = None
    if not args.no_tray:
        from .tray import start_tray

        def quit_app():
            hud.after(0, hud._quit)

        tray_icon = start_tray(
            cfg,
            bus,
            service,
            on_show=lambda: hud.after(0, hud.show),
            on_settings=lambda: hud.after(0, hud.open_settings),
            on_quit=quit_app,
        )
        hud.on_quit(lambda: tray_icon and tray_icon.stop())

    # ---- go -----------------------------------------------------------------
    service.start()
    hud._log("Ultron online. Say \"Ultron\", press Ctrl+Alt+U, or type a command.", "system")

    if first_run:
        hud.after(600, hud.open_wizard)
    if args.settings:
        hud.after(700, hud.open_settings)
    if args.minimized or cfg.get("behavior.start_minimized", False):
        hud.after(100, hud.withdraw)

    try:
        hud.mainloop()
    finally:
        service.shutdown()
        try:
            lock.close()
        except OSError:
            pass
    lg.info("Ultron terminated")
    return 0


if __name__ == "__main__":
    sys.exit(run())
