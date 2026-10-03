"""System tray icon (pystray)."""

from __future__ import annotations

import threading


def start_tray(cfg, bus, service, on_show, on_settings, on_quit) -> "object | None":
    """Run the tray icon in a daemon thread. Returns the Icon or None."""
    try:
        import pystray
        from PIL import Image
    except Exception as exc:
        from . import log

        log.get().warning("tray unavailable: %s", exc)
        return None

    from .paths import resource

    icon_path = resource("assets/icons/icon.png")
    try:
        image = Image.open(str(icon_path))
    except Exception:
        image = Image.new("RGBA", (64, 64), (200, 30, 30, 255))

    def _show(icon, item):
        on_show()

    def _settings(icon, item):
        on_settings()

    def _mute(icon, item):
        service.set_muted(not service.muted)

    def _quit(icon, item):
        on_quit()

    menu = pystray.Menu(
        pystray.MenuItem("Show HUD", _show, default=True),
        pystray.MenuItem("Settings", _settings),
        pystray.MenuItem(lambda text: "Unmute microphone" if service.muted else "Mute microphone", _mute),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Shut down Ultron", _quit),
    )

    icon = pystray.Icon("Ultron", image, "Ultron — voice assistant", menu)

    def _run():
        try:
            icon.run()
        except Exception:
            from . import log

            log.get().exception("tray loop crashed")

    threading.Thread(target=_run, name="ultron-tray", daemon=True).start()
    return icon
