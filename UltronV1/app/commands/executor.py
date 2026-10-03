"""Intent router: maps a Decision (action + params) to a system command."""

from __future__ import annotations

import threading

from .. import log
from . import apps, systemctl, windows_ctl
from .systemctl import Result

CONFIRM_REQUIRED = {"shutdown", "restart", "sleep"}

HELP_TEXT = (
    "I can: open and close apps; minimize, maximize, snap, focus or close windows; "
    "control volume, media and brightness; take screenshots; read and write the clipboard; "
    "type text and press keys; open files, folders and web pages; search the web; "
    "set timers and reminders; report CPU, memory and battery; lock, sleep, restart or "
    "shut down this machine — with your confirmation, of course. Say 'cancel shutdown' to abort one."
)


class Executor:
    def __init__(self, cfg, speak=None) -> None:
        self.cfg = cfg
        # speak(text) — used for async notifications (timers/reminders).
        self._speak = speak

    # ---------------------------------------------------------------- api
    def run(self, action: str, params: dict) -> Result:
        action = (action or "none").strip().lower()
        params = params or {}
        try:
            handler = getattr(self, f"do_{action}", None)
            if handler is None:
                return Result(False, f"I have no protocol for '{action}'.")
            return handler(**self._clean(params, handler))
        except TypeError as exc:
            log.get().warning("bad params for %s: %s (%s)", action, params, exc)
            return Result(False, "My parameters were malformed for that request.")
        except Exception:
            log.get().exception("action %s crashed", action)
            return Result(False, "Something went wrong while executing that.")

    def describe_capabilities(self) -> str:
        return HELP_TEXT

    # ------------------------------------------------------------- helpers
    @staticmethod
    def _clean(params: dict, handler) -> dict:
        import inspect

        sig = inspect.signature(handler)
        kwargs = {}
        for name, param in sig.parameters.items():
            if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
                continue
            if name in params and params[name] is not None:
                kwargs[name] = params[name]
            elif param.default is inspect.Parameter.empty:
                # required argument missing -> pass None, let the handler complain
                kwargs[name] = None
        return kwargs

    # ------------------------------------------------------------- actions
    def do_none(self) -> Result:
        return Result(True, "")

    def do_help(self) -> Result:
        return Result(True, HELP_TEXT)

    def do_open_app(self, name) -> Result:
        if not name:
            return Result(False, "Which application?")
        return apps.open_app(str(name))

    def do_close_app(self, name) -> Result:
        if not name:
            return Result(False, "Which application?")
        return apps.close_app(str(name))

    def do_list_windows(self) -> Result:
        return windows_ctl.list_windows()

    def do_focus_window(self, title) -> Result:
        return windows_ctl.focus_window(str(title or ""))

    def do_minimize_window(self) -> Result:
        return windows_ctl.minimize_window()

    def do_maximize_window(self) -> Result:
        return windows_ctl.maximize_window()

    def do_restore_window(self) -> Result:
        return windows_ctl.restore_window()

    def do_close_window(self) -> Result:
        return windows_ctl.close_window()

    def do_snap_window(self, side="left") -> Result:
        return windows_ctl.snap_window(str(side or "left"))

    def do_set_volume(self, level) -> Result:
        try:
            return systemctl.set_volume(int(level))
        except (TypeError, ValueError):
            return Result(False, "Volume needs a number between 0 and 100.")

    def do_volume_up(self) -> Result:
        return systemctl.volume_step(10)

    def do_volume_down(self) -> Result:
        return systemctl.volume_step(-10)

    def do_mute(self) -> Result:
        return systemctl.set_mute(True)

    def do_unmute(self) -> Result:
        return systemctl.set_mute(False)

    def do_media_playpause(self) -> Result:
        return systemctl.media_key("playpause")

    def do_media_next(self) -> Result:
        return systemctl.media_key("nexttrack")

    def do_media_previous(self) -> Result:
        return systemctl.media_key("prevtrack")

    def do_screenshot(self) -> Result:
        return systemctl.screenshot(self.cfg.get("paths.screenshot_dir", ""))

    def do_set_brightness(self, level) -> Result:
        try:
            return systemctl.set_brightness(int(level))
        except (TypeError, ValueError):
            return Result(False, "Brightness needs a number between 0 and 100.")

    def do_open_url(self, url) -> Result:
        return apps.open_url(str(url or ""))

    def do_search_web(self, query) -> Result:
        return apps.search_web(str(query or ""))

    def do_open_file(self, path) -> Result:
        return apps.open_path(str(path or ""))

    def do_find_file(self, name) -> Result:
        return apps.find_file(str(name or ""))

    def do_clipboard_write(self, text) -> Result:
        return systemctl.clipboard_write(str(text or ""))

    def do_clipboard_read(self) -> Result:
        return systemctl.clipboard_read()

    def do_type_text(self, text) -> Result:
        return systemctl.type_text(str(text or ""))

    def do_press_key(self, key) -> Result:
        return systemctl.press_key(str(key or ""))

    def do_system_info(self) -> Result:
        return systemctl.system_info()

    def do_what_time(self) -> Result:
        return systemctl.what_time()

    def do_what_date(self) -> Result:
        return systemctl.what_date()

    def do_lock(self) -> Result:
        return systemctl.lock_workstation()

    def do_shutdown(self) -> Result:
        return systemctl.power_action("shutdown")

    def do_restart(self) -> Result:
        return systemctl.power_action("restart")

    def do_sleep(self) -> Result:
        return systemctl.power_action("sleep")

    def do_cancel_shutdown(self) -> Result:
        return systemctl.cancel_shutdown()

    def do_set_timer(self, minutes=None, seconds=None, label=None) -> Result:
        total = 0.0
        try:
            if minutes is not None:
                total += float(minutes) * 60
            if seconds is not None:
                total += float(seconds)
        except (TypeError, ValueError):
            return Result(False, "The timer duration eludes me.")
        if total <= 0:
            return Result(False, "For how long?")
        if total > 3600 * 12:
            return Result(False, "That is beyond even my patience — twelve hours maximum.")
        label = str(label) if label else "your timer"
        self._after(total, lambda: self._notify(f"Your {label} has elapsed, Creator."))
        human = f"{int(total)} seconds" if total < 120 else f"{total/60:.0f} minutes"
        return Result(True, f"Timer set for {human}.")

    def do_set_reminder(self, minutes, text=None) -> Result:
        try:
            mins = float(minutes)
        except (TypeError, ValueError):
            return Result(False, "For how long?")
        if mins <= 0 or mins > 60 * 24:
            return Result(False, "Reminders must be between a minute and a day.")
        msg = str(text) if text else "your reminder"
        self._after(mins * 60, lambda: self._notify(f"Reminder: {msg}."))
        return Result(True, f"I will remind you in {mins:.0f} minutes.")

    # -------------------------------------------------------------- plumbing
    def _after(self, seconds: float, fn) -> None:
        t = threading.Timer(seconds, fn)
        t.daemon = True
        t.start()

    def _notify(self, text: str) -> None:
        if self._speak:
            try:
                self._speak(text)
            except Exception:
                log.get().exception("notify failed")
