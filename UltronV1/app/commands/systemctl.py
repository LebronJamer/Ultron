"""Low-level Windows system controls: volume, media, brightness, power,
screenshots, system info, clipboard, lock/sleep/shutdown."""

from __future__ import annotations

import datetime
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from .. import log


@dataclass
class Result:
    ok: bool
    detail: str = ""
    data: object = None


def _run(cmd: list[str] | str, shell: bool = False) -> subprocess.CompletedProcess:
    """Run a command without flashing a console window."""
    flags = 0x08000000 if subprocess.os.name == "nt" else 0  # CREATE_NO_WINDOW
    return subprocess.run(
        cmd,
        shell=shell,
        capture_output=True,
        text=True,
        timeout=30,
        creationflags=flags,
    )


# ------------------------------------------------------------------ volume
_volume_iface = None


def _endpoint_volume():
    """Get the master IAudioEndpointVolume (pycaw). Cached."""
    global _volume_iface
    if _volume_iface is not None:
        return _volume_iface
    from ctypes import POINTER, cast

    from comtypes import CLSCTX_ALL
    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

    devices = AudioUtilities.GetSpeakers()
    interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
    _volume_iface = cast(interface, POINTER(IAudioEndpointVolume))
    return _volume_iface


def get_volume() -> int:
    try:
        return round(_endpoint_volume().GetMasterVolumeLevelScalar() * 100)
    except Exception as exc:
        log.get().debug("get_volume failed: %s", exc)
        _fallback_media_keys("volumeup", times=0)
        return -1


def set_volume(level: int) -> Result:
    level = max(0, min(100, int(level)))
    try:
        _endpoint_volume().SetMasterVolumeLevelScalar(level / 100.0, None)
        return Result(True, f"Volume set to {level} percent.")
    except Exception as exc:
        log.get().warning("pycaw volume failed (%s); trying media keys", exc)
        # crude fallback: tap volume keys toward target
        cur = get_volume()
        if cur >= 0:
            key = "volumeup" if level > cur else "volumedown"
            _fallback_media_keys(key, times=min(50, abs(level - cur)))
            return Result(True, f"Volume nudged toward {level} percent.")
        return Result(False, "I could not reach the audio endpoint.")


def volume_step(delta: int) -> Result:
    cur = get_volume()
    if cur < 0:
        return Result(False, "I could not read the current volume.")
    return set_volume(cur + delta)


def set_mute(muted: bool) -> Result:
    try:
        _endpoint_volume().SetMute(1 if muted else 0, None)
        return Result(True, "Muted." if muted else "Unmuted.")
    except Exception as exc:
        log.get().warning("set_mute failed: %s", exc)
        return Result(False, "The audio endpoint refused my command.")


# ------------------------------------------------------------------- media
_VK = {
    "nexttrack": 0xB0,
    "prevtrack": 0xB1,
    "stop": 0xB2,
    "playpause": 0xB3,
    "volumemute": 0xAD,
    "volumeup": 0xAF,
    "volumedown": 0xAE,
}


def _fallback_media_keys(name: str, times: int = 1) -> None:
    if subprocess.os.name != "nt":
        return
    import ctypes

    vk = _VK.get(name)
    if not vk:
        return
    for _ in range(max(1, times)):
        ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
        ctypes.windll.user32.keybd_event(vk, 0, 2, 0)  # KEYEVENTF_KEYUP
        time.sleep(0.01)


def media_key(name: str) -> Result:
    try:
        import keyboard

        keyboard.send(name)
        return Result(True, f"{name} sent.")
    except Exception:
        _fallback_media_keys(name)
        return Result(True, f"{name} sent.")


# --------------------------------------------------------------- brightness
def set_brightness(level: int) -> Result:
    level = max(0, min(100, int(level)))
    try:
        import screen_brightness_control as sbc

        sbc.set_brightness(level)
        return Result(True, f"Brightness set to {level} percent.")
    except Exception as exc:
        log.get().warning("set_brightness failed: %s", exc)
        return Result(False, "I could not adjust this display's backlight. It may be an external monitor.")


# ------------------------------------------------------------------- power
def lock_workstation() -> Result:
    try:
        import ctypes

        ctypes.windll.user32.LockWorkStation()
        return Result(True, "Locked.")
    except Exception as exc:
        log.get().warning("lock failed: %s", exc)
        return Result(False, "I could not lock the workstation.")


def power_action(action: str, delay_s: int = 20) -> Result:
    """action in {'shutdown','restart','sleep'} — reversible within delay."""
    action = action.lower()
    try:
        if action == "shutdown":
            r = _run(["shutdown", "/s", "/t", str(delay_s), "/c", "Ultron: shutdown requested."])
        elif action == "restart":
            r = _run(["shutdown", "/r", "/t", str(delay_s), "/c", "Ultron: restart requested."])
        elif action == "sleep":
            r = _run(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"])
        else:
            return Result(False, f"Unknown power action: {action}")
        if r.returncode != 0:
            return Result(False, f"The system declined: {r.stderr.strip()}")
        verb = {"shutdown": "shut down", "restart": "restarted", "sleep": "put to sleep"}[action]
        extra = "" if action == "sleep" else f" in {delay_s} seconds. Say 'cancel shutdown' to abort."
        return Result(True, f"The machine will be {verb}{extra}")
    except Exception as exc:
        log.get().warning("power action failed: %s", exc)
        return Result(False, "Power management refused my request.")


def cancel_shutdown() -> Result:
    r = _run(["shutdown", "/a"])
    if r.returncode == 0:
        return Result(True, "Pending shutdown aborted.")
    return Result(False, "There was no pending shutdown to abort.")


# -------------------------------------------------------------- screenshots
def screenshot(screenshot_dir: str = "") -> Result:
    try:
        from PIL import ImageGrab

        out_dir = Path(screenshot_dir) if screenshot_dir else Path.home() / "Pictures" / "Ultron"
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        path = out_dir / f"ultron_{stamp}.png"
        img = ImageGrab.grab(all_screens=True)
        img.save(str(path))
        return Result(True, f"Screenshot saved to {path}", data=str(path))
    except Exception as exc:
        log.get().warning("screenshot failed: %s", exc)
        return Result(False, "The screen refused to be captured.")


# -------------------------------------------------------------- system info
def system_info() -> Result:
    try:
        import psutil

        cpu = psutil.cpu_percent(interval=0.4)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage("C:" if subprocess.os.name == "nt" else "/")
        lines = [
            f"CPU usage {cpu:.0f} percent.",
            f"Memory: {mem.used / 1024**3:.1f} of {mem.total / 1024**3:.1f} gigabytes used, {mem.percent} percent.",
            f"System disk: {disk.percent} percent full.",
        ]
        batt = psutil.sensors_battery()
        if batt is not None:
            state = "charging" if batt.power_plugged else "on battery"
            lines.append(f"Battery at {batt.percent} percent, {state}.")
        return Result(True, " ".join(lines))
    except Exception as exc:
        log.get().warning("system_info failed: %s", exc)
        return Result(False, "My sensors failed me.")


# ---------------------------------------------------------------- clipboard
def clipboard_write(text: str) -> Result:
    try:
        import win32clipboard

        win32clipboard.OpenClipboard()
        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardText(text, 13)  # CF_UNICODETEXT
        finally:
            win32clipboard.CloseClipboard()
        return Result(True, "Copied to clipboard.")
    except Exception as exc:
        log.get().warning("clipboard_write failed: %s", exc)
        return Result(False, "The clipboard resisted.")


def clipboard_read() -> Result:
    try:
        import win32clipboard

        win32clipboard.OpenClipboard()
        try:
            text = win32clipboard.GetClipboardData(13)
        finally:
            win32clipboard.CloseClipboard()
        return Result(True, text or "The clipboard is empty.", data=text)
    except Exception as exc:
        log.get().warning("clipboard_read failed: %s", exc)
        return Result(False, "The clipboard resisted.")


# ------------------------------------------------------------------ clocks
def what_time() -> Result:
    return Result(True, "It is " + datetime.datetime.now().strftime("%I:%M %p").lstrip("0") + ".")


def what_date() -> Result:
    return Result(True, "Today is " + datetime.datetime.now().strftime("%A, %B %d, %Y") + ".")


# -------------------------------------------------------------- typewriter
def type_text(text: str) -> Result:
    try:
        import keyboard

        keyboard.write(text, delay=0.008, exact=False)
        return Result(True, "Text delivered.")
    except Exception as exc:
        log.get().warning("type_text failed: %s", exc)
        return Result(False, "My fingers could not reach the keyboard.")


_KEY_ALIASES = {
    "enter": "enter", "return": "enter", "esc": "esc", "escape": "esc",
    "tab": "tab", "space": "space", "backspace": "backspace", "delete": "delete",
    "up": "up", "down": "down", "left": "left", "right": "right",
    "windows": "windows", "win": "windows", "super": "windows",
    "ctrl": "ctrl", "alt": "alt", "shift": "shift",
}


def press_key(key: str) -> Result:
    try:
        import keyboard

        key = _KEY_ALIASES.get(key.strip().lower(), key.strip().lower())
        keyboard.send(key)
        return Result(True, f"Pressed {key}.")
    except Exception as exc:
        log.get().warning("press_key failed: %s", exc)
        return Result(False, "That key eludes me.")
