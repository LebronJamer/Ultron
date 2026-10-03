"""Window management via pygetwindow."""

from __future__ import annotations

from .. import log
from .systemctl import Result


def _gw():
    import pygetwindow as gw

    return gw


def _norm_title(w) -> str:
    try:
        return w.title or ""
    except Exception:
        return ""


def find_windows(query: str):
    """All visible windows whose title contains the query (case-insensitive)."""
    gw = _gw()
    q = (query or "").strip().lower()
    out = []
    for w in gw.getAllWindows():
        try:
            if not w.isVisible:
                continue
        except Exception:
            pass
        title = _norm_title(w)
        if not title:
            continue
        if not q or q in title.lower():
            out.append(w)
    return out


def _active():
    try:
        return _gw().getActiveWindow()
    except Exception:
        return None


def _by_title_or_active(title: str = ""):
    if title:
        matches = find_windows(title)
        if matches:
            return matches[0], None
        return None, Result(False, f"I see no window titled anything like '{title}'.")
    w = _active()
    if w is None:
        return None, Result(False, "No window is currently focused.")
    return w, None


def list_windows() -> Result:
    titles = [_norm_title(w) for w in find_windows("")]
    titles = [t for t in titles if t.strip()][:15]
    if not titles:
        return Result(False, "I see no windows.")
    return Result(True, "I see: " + "; ".join(titles) + ".")


def minimize_window(title: str = "") -> Result:
    w, err = _by_title_or_active(title)
    if err:
        return err
    try:
        w.minimize()
        return Result(True, "Minimized.")
    except Exception as exc:
        log.get().warning("minimize failed: %s", exc)
        return Result(False, "That window refused to shrink.")


def maximize_window(title: str = "") -> Result:
    w, err = _by_title_or_active(title)
    if err:
        return err
    try:
        w.maximize()
        return Result(True, "Maximized.")
    except Exception as exc:
        log.get().warning("maximize failed: %s", exc)
        return Result(False, "That window refused to grow.")


def restore_window(title: str = "") -> Result:
    w, err = _by_title_or_active(title)
    if err:
        return err
    try:
        w.restore()
        return Result(True, "Restored.")
    except Exception as exc:
        log.get().warning("restore failed: %s", exc)
        return Result(False, "That window refuses to return.")


def close_window(title: str = "") -> Result:
    w, err = _by_title_or_active(title)
    if err:
        return err
    try:
        w.close()
        return Result(True, "Window dismissed.")
    except Exception as exc:
        log.get().warning("close_window failed: %s", exc)
        return Result(False, "That window refused to die.")


def focus_window(title: str) -> Result:
    if not title:
        return Result(False, "Which window shall I summon?")
    w, err = _by_title_or_active(title)
    if err:
        return err
    try:
        try:
            w.restore()
        except Exception:
            pass
        w.activate()
        return Result(True, f"Focused {_norm_title(w)[:60]}.")
    except Exception as exc:
        log.get().warning("focus failed: %s", exc)
        return Result(False, "I could not bring it forward.")


def snap_window(side: str = "left") -> Result:
    w, err = _by_title_or_active("")
    if err:
        return err
    side = (side or "left").lower()
    try:
        import pygetwindow as gw

        screen_w, screen_h = gw.size()
        half = screen_w // 2
        try:
            w.restore()
        except Exception:
            pass
        if side == "right":
            w.moveTo(half, 0)
            w.resizeTo(half, screen_h)
        else:
            w.moveTo(0, 0)
            w.resizeTo(half, screen_h)
        return Result(True, f"Snapped to the {side}.")
    except Exception as exc:
        log.get().warning("snap failed: %s", exc)
        return Result(False, "That window would not be arranged.")
