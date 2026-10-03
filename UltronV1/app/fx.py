"""The ULTRON voice: a real-time post-processing chain applied to raw TTS.

All DSP is plain numpy so it bundles cleanly with PyInstaller and runs fast
on CPU. The chain turns a plain SAPI voice into a deep, metallic, slightly
reverberant machine voice:

    1. pitch-down / slow-down (resampling — also makes delivery deliberate)
    2. detuned robotic chorus (two short delayed copies, micro pitch offsets)
    3. ring modulation (adds metallic sidebands)
    4. soft saturation (tanh — gives it a driven, "powered" edge)
    5. FFT equalisation (low-shelf boost + gentle low-pass = dark timbre)
    6. convolution reverb with a short synthetic impulse response
    7. normalisation + edge gating

Note: this is an original synthesized character voice inspired by cinematic
AI antagonists. It is not a clone of any actor's voice.
"""

from __future__ import annotations

import numpy as np


# ------------------------------------------------------------- primitives
def _resample(x: np.ndarray, factor: float) -> np.ndarray:
    """Linear resample. factor > 1 -> longer & deeper; factor < 1 -> shorter & higher."""
    if factor <= 0 or not len(x):
        return x.copy()
    n = max(2, int(round(len(x) * factor)))
    return np.interp(
        np.linspace(0.0, len(x) - 1.0, n), np.arange(len(x), dtype=np.float64), x
    )


def _delay(x: np.ndarray, samples: int) -> np.ndarray:
    if samples <= 0:
        return x.copy()
    out = np.zeros(len(x) + samples)
    out[samples:] = x
    return out


def _low_shelf_curve(freqs: np.ndarray, f0: float, gain_db: float) -> np.ndarray:
    """+gain below f0, unity above."""
    g = 10 ** (gain_db / 20)
    return 1.0 + (g - 1.0) / (1.0 + (freqs / max(f0, 1.0)) ** 2)


def _lowpass_curve(freqs: np.ndarray, fc: float, order: float = 3.0) -> np.ndarray:
    return 1.0 / np.sqrt(1.0 + (freqs / max(fc, 1.0)) ** (2 * order))


def _fft_filter(x: np.ndarray, sr: int, curve_fn) -> np.ndarray:
    if not len(x):
        return x
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), d=1.0 / sr)
    return np.fft.irfft(X * curve_fn(f), n=len(x))


def _reverb_ir(sr: int, decay_s: float = 0.09, length_s: float = 0.22) -> np.ndarray:
    n = int(sr * length_s)
    rng = np.random.default_rng(1997)
    t = np.arange(n) / sr
    ir = rng.standard_normal(n) * np.exp(-t / decay_s)
    ir[: int(sr * 0.003)] = 0  # pre-delay
    ir /= np.max(np.abs(ir)) + 1e-9
    return ir


def _fft_convolve(x: np.ndarray, h: np.ndarray) -> np.ndarray:
    n = len(x) + len(h) - 1
    nfft = 1 << (n - 1).bit_length()
    X = np.fft.rfft(x, nfft)
    H = np.fft.rfft(h, nfft)
    return np.fft.irfft(X * H, nfft)[:n]


def _gate_edges(x: np.ndarray, sr: int, hold_ms: float = 60.0) -> np.ndarray:
    """Silence the head/tail beyond speech — keeps noise floor black."""
    win = max(1, int(sr * 0.02))
    if len(x) < 3 * win:
        return x
    env = np.convolve(np.abs(x), np.ones(win) / win, mode="same")
    thresh = max(0.02, 0.15 * float(np.max(env)))
    active = np.where(env > thresh)[0]
    if not len(active):
        return x
    pad = int(sr * hold_ms / 1000)
    a = max(0, int(active[0]) - pad)
    b = min(len(x), int(active[-1]) + pad)
    out = np.zeros_like(x)
    out[a:b] = x[a:b]
    return out


# ------------------------------------------------------------------ chain
def ultronize(
    x: np.ndarray,
    sr: int,
    intensity: float = 1.0,
    extra_pitch_semitones: float = 2.5,
) -> np.ndarray:
    """Apply the ULTRON voice chain to a float mono signal in [-1, 1]."""
    if x is None or not len(x):
        return x
    i = max(0.0, min(1.5, float(intensity)))
    y = np.asarray(x, dtype=np.float64)

    # 1) deepen + slow (resample to a longer signal, play at original rate)
    if extra_pitch_semitones > 0:
        y = _resample(y, 2.0 ** (extra_pitch_semitones / 12.0))

    # 2) detuned robotic chorus
    d1 = _delay(_resample(y, 1.004), int(0.011 * sr))
    d2 = _delay(_resample(y, 0.996), int(0.017 * sr))
    n = min(len(y), len(d1), len(d2))
    y = 0.64 * y[:n] + 0.18 * d1[:n] + 0.18 * d2[:n]

    # 3) ring modulation (metallic sidebands), mixed with dry
    t = np.arange(len(y)) / sr
    ring = np.sin(2 * np.pi * 57.0 * t) * np.sin(2 * np.pi * 0.7 * t)
    mix = 0.30 * i
    y = (1.0 - mix) * y + mix * y * ring

    # 4) soft saturation
    k = 1.0 + 0.6 * i
    y = np.tanh(k * y) / np.tanh(k)

    # 5) dark timbre: +2.5 dB low shelf @ 170 Hz, gentle LPF @ 4.2 kHz
    y = _fft_filter(
        y,
        sr,
        lambda f: _low_shelf_curve(f, 170.0, 2.5 + 1.0 * i)
        * _lowpass_curve(f, 4200.0 - 600.0 * i, order=2.5),
    )

    # 6) short dark reverb (convolution with synthetic impulse response)
    if i > 0:
        wet = _fft_convolve(y, _reverb_ir(sr))
        wet *= 0.11 * i
        out = np.zeros(len(wet))
        out[: len(y)] = y
        y = out + wet


    # 7) gate, normalise
    y = _gate_edges(y, sr)
    peak = float(np.max(np.abs(y))) if len(y) else 0.0
    if peak > 1e-9:
        y *= 0.85 / peak
    return y
