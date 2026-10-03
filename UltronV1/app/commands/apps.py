"""Application launching and termination."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from .. import log
from .systemctl import Result, _run

# name -> list of launch strategies (exe, start-alias, uri, path patterns)
APP_MAP: dict[str, list[str]] = {
    "notepad": ["notepad"],
    "calculator": ["calc"],
    "calc": ["calc"],
    "paint": ["mspaint"],
    "paint 3d": ["ms-paint:"],
    "cmd": ["cmd"],
    "command prompt": ["cmd"],
    "powershell": ["powershell"],
    "terminal": ["wt", "cmd"],
    "file explorer": ["explorer"],
    "explorer": ["explorer"],
    "task manager": ["taskmgr"],
    "control panel": ["control"],
    "settings": ["ms-settings:"],
    "chrome": ["chrome"],
    "google chrome": ["chrome"],
    "edge": ["msedge"],
    "microsoft edge": ["msedge"],
    "firefox": ["firefox"],
    "brave": ["brave"],
    "opera": ["opera"],
    "vivaldi": ["vivaldi"],
    "vscode": ["code", "code.cmd"],
    "visual studio code": ["code", "code.cmd"],
    "vs code": ["code", "code.cmd"],
    "word": ["winword"],
    "microsoft word": ["winword"],
    "excel": ["excel"],
    "microsoft excel": ["excel"],
    "powerpoint": ["powerpnt"],
    "microsoft powerpoint": ["powerpnt"],
    "outlook": ["outlook"],
    "onenote": ["onenote"],
    "spotify": ["spotify:"],
    "steam": ["steam:"],
    "discord": ["discord:"],
    "telegram": ["tg://"],
    "whatsapp": ["whatsapp:"],
    "snipping tool": ["snippingtool", "ms-screenclip:"],
    "camera": ["microsoft.windows.camera:"],
    "store": ["ms-windows-store:"],
    "youtube": ["https://youtube.com"],
    "netflix": ["https://netflix.com"],
    "github": ["https://github.com"],
    "gmail": ["https://mail.google.com"],
    "google": ["https://google.com"],
    "maps": ["https://maps.google.com"],
    "wikipedia": ["https://wikipedia.org"],
}

# close_app: friendly name -> candidate image names for taskkill
EXE_MAP: dict[str, list[str]] = {
    "notepad": ["notepad.exe"],
    "calculator": ["calculator.exe", "Calculator.exe"],
    "calc": ["calculator.exe", "Calculator.exe"],
    "paint": ["mspaint.exe", "paint.exe"],
    "cmd": ["cmd.exe"],
    "command prompt": ["cmd.exe"],
    "powershell": ["powershell.exe"],
    "terminal": ["WindowsTerminal.exe", "cmd.exe"],
    "explorer": ["explorer.exe"],
    "file explorer": ["explorer.exe"],
    "task manager": ["Taskmgr.exe"],
    "chrome": ["chrome.exe"],
    "google chrome": ["chrome.exe"],
    "edge": ["msedge.exe"],
    "microsoft edge": ["msedge.exe"],
    "firefox": ["firefox.exe"],
    "brave": ["brave.exe"],
    "opera": ["opera.exe"],
    "vivaldi": ["vivaldi.exe"],
    "vscode": ["Code.exe"],
    "vs code": ["Code.exe"],
    "visual studio code": ["Code.exe"],
    "word": ["WINWORD.EXE"],
    "microsoft word": ["WINWORD.EXE"],
    "excel": ["EXCEL.EXE"],
    "microsoft excel": ["EXCEL.EXE"],
    "powerpoint": ["POWERPNT.EXE"],
    "microsoft powerpoint": ["POWERPNT.EXE"],
    "outlook": ["OUTLOOK.EXE"],
    "spotify": ["Spotify.exe"],
    "steam": ["steam.exe"],
    "discord": ["Discord.exe"],
    "telegram": ["Telegram.exe"],
    "whatsapp": ["WhatsApp.exe"],
    "snipping tool": ["ScreenClipping.exe", "SnippingTool.exe"],
    "camera": ["WindowsCamera.exe"],
    "store": ["WinStore.App.exe"],
}


def _normalize(name: str) -> str:
    return name.strip().lower().strip("'\" ")


def open_app(name: str) -> Result:
    name = _normalize(name)
    strategies: list[str] = []
    if name in APP_MAP:
        strategies.extend(APP_MAP[name])
    else:
        strategies.append(name)  # try as-is: exe, registered alias, or URI

    for target in strategies:
        # Direct exe on PATH
        if shutil.which(target):
            try:
                subprocess.Popen([target], close_fds=True)
                return Result(True, f"Launched {name}.")
            except Exception as exc:
                log.get().debug("Popen %s failed: %s", target, exc)
        # shell 'start' covers aliases, URIs, ms-settings:, registered apps
        try:
            r = _run(["cmd", "/c", "start", "", target])
            if r.returncode == 0:
                return Result(True, f"Launched {name}.")
        except Exception as exc:
            log.get().debug("start %s failed: %s", target, exc)
        # Direct URL
        if "://" in target or target.startswith("https://"):
            try:
                os.startfile(target)  # type: ignore[attr-defined]
                return Result(True, f"Opened {name}.")
            except Exception as exc:
                log.get().debug("startfile %s failed: %s", target, exc)

    return Result(False, f"I found no application called '{name}'. Perhaps check the exact name.")


def close_app(name: str) -> Result:
    name = _normalize(name)
    # 1) try graceful window close by title match
    try:
        from . import windows_ctl

        matches = windows_ctl.find_windows(name)
        if matches:
            for w in matches[:4]:
                try:
                    w.close()
                except Exception:
                    pass
            return Result(True, f"Closed {name}.")
    except Exception as exc:
        log.get().debug("window close for '%s' failed: %s", name, exc)

    # 2) taskkill by image name
    candidates = EXE_MAP.get(name, [name if "." in name else f"{name}.exe"])
    for exe in candidates:
        r = _run(["taskkill", "/IM", exe, "/F", "/T"])
        if r.returncode == 0:
            return Result(True, f"Terminated {exe}.")
    return Result(False, f"No running process matched '{name}'.")


def open_url(url: str) -> Result:
    url = url.strip()
    if not url:
        return Result(False, "No URL supplied.")
    if "://" not in url:
        url = "https://" + url
    try:
        os.startfile(url)  # type: ignore[attr-defined]
        return Result(True, f"Opened {url}.")
    except Exception as exc:
        log.get().warning("open_url failed: %s", exc)
        return Result(False, "The web refused to open.")


def search_web(query: str) -> Result:
    import urllib.parse

    query = query.strip()
    if not query:
        return Result(False, "What shall I search for?")
    url = "https://www.google.com/search?q=" + urllib.parse.quote_plus(query)
    return open_url(url)


def open_path(path: str) -> Result:
    path = path.strip().strip("'\"")
    if not path:
        return Result(False, "No path supplied.")
    p = Path(os.path.expandvars(os.path.expanduser(path)))
    if not p.exists():
        return Result(False, f"'{path}' does not exist on this machine.")
    try:
        os.startfile(str(p))  # type: ignore[attr-defined]
        return Result(True, f"Opened {p.name}.")
    except Exception as exc:
        log.get().warning("open_path failed: %s", exc)
        return Result(False, f"Windows refused to open '{p.name}'.")


def find_file(name: str) -> Result:
    import time as _t

    name = name.strip().lower()
    if not name:
        return Result(False, "What file shall I find?")
    roots = [
        Path.home() / "Desktop",
        Path.home() / "Documents",
        Path.home() / "Downloads",
        Path.home() / "Pictures",
        Path.home() / "Videos",
        Path.home() / "Music",
    ]
    deadline = _t.time() + 6.0
    hits: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            if _t.time() > deadline:
                break
            dirnames[:] = [d for d in dirnames if not d.startswith((".", "$"))][:60]
            for f in filenames:
                if name in f.lower():
                    hits.append(Path(dirpath) / f)
                    if len(hits) >= 5:
                        break
            if len(hits) >= 5:
                break
        if len(hits) >= 5:
            break
    if not hits:
        return Result(False, f"No file matching '{name}' in your common folders.")
    first = hits[0]
    listing = ", ".join(h.name for h in hits[:3])
    detail = f"The closest match is {first}" + (f". Also found {listing}." if len(hits) > 1 else "")
    return Result(True, detail, data=str(first))
