"""Audio playback helpers and UI sound cues (all synthesized, no assets)."""

from __future__ import annotations

import numpy as np

try:
    import sounddevice as _sd

    HAVE_SD = True
except Exception:  # pragma: no cover
    _sd = None
    HAVE_SD = False

SR = 22050


# --------------------------------------------------------------- playback
def play(data: np.ndarray, sr: int, blocking: bool = False) -> None:
    """Play a float mono signal in [-1, 1]."""
    if not HAVE_SD:
        return
    x = np.asarray(data, dtype=np.float32)
    _sd.play(x, sr, blocking=blocking)


def stop() -> None:
    if HAVE_SD:
        _sd.stop()


# ------------------------------------------------------------------ cues
def _tone(
    freq: float,
    dur: float,
    harmonics: tuple[tuple[float, float], ...] = ((1.0, 1.0), (2.0, 0.30), (3.0, 0.12)),
    decay: float = 7.0,
    sr: int = SR,
) -> np.ndarray:
    t = np.arange(int(sr * dur)) / sr
    y = np.zeros_like(t)
    for mult, amp in harmonics:
        y += amp * np.sin(2 * np.pi * freq * mult * t)
    y *= np.exp(-decay * t)
    return y


def _fade(x: np.ndarray, ms: float = 8.0, sr: int = SR) -> np.ndarray:
    n = max(1, int(sr * ms / 1000))
    if len(x) <= 2 * n:
        return x
    env = np.ones_like(x)
    env[:n] = np.linspace(0, 1, n)
    env[-n:] = np.linspace(1, 0, n)
    return x * env


def _norm(x: np.ndarray, peak: float = 0.5) -> np.ndarray:
    m = float(np.max(np.abs(x))) if len(x) else 0.0
    return x * (peak / m) if m > 1e-9 else x


def activation_cue() -> tuple[np.ndarray, int]:
    """Low ominous rising chime — 'Ultron is awake'."""
    y = np.concatenate(
        [
            _tone(174.6, 0.12, decay=9),
            _tone(261.6, 0.14, decay=8),
            _tone(349.2, 0.30, decay=6),
        ]
    )
    return _norm(_fade(y)), SR


def ack_cue() -> tuple[np.ndarray, int]:
    """Short soft blip — command accepted."""
    return _norm(_fade(_tone(392.0, 0.09, decay=12))), SR


def error_cue() -> tuple[np.ndarray, int]:
    """Low buzz — something failed."""
    t = np.arange(int(SR * 0.30)) / SR
    y = np.sign(np.sin(2 * np.pi * 92 * t)) * 0.4
    y = np.minimum(np.maximum(y * np.exp(-3 * t), -0.4), 0.4)
    y += 0.25 * np.sin(2 * np.pi * 91 * t) * np.exp(-3 * t)  # slow beat
    return _norm(_fade(y, 15)), SR
