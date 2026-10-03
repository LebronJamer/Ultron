"""Text-to-speech via the Windows SAPI5 voice engine (win32com).

We drive SAPI directly (rather than through pyttsx3) so we can use SAPI's
XML pitch control and stream to a WAV file. The raw voice is then heavily
processed by ``fx.ultronize`` to produce the machine voice.
"""

from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

from . import log

_MALE_HINTS = ("david", "mark", "george", "guy", "eric", "james", "daniel", "ryan", "thomas", "alex")


def _escape_sapi(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


class SapiSynth:
    """Synthesizes text to a raw float mono array. Windows only."""

    def __init__(self) -> None:
        self._voice = None
        self._voice_desc = ""

    # ---------------------------------------------------------------- api
    def list_voices(self) -> list[str]:
        try:
            import pythoncom
            import win32com.client

            pythoncom.CoInitialize()
            sp = win32com.client.Dispatch("SAPI.SpVoice")
            names = []
            for i in range(sp.GetVoices().Count):
                names.append(str(sp.GetVoices().Item(i).GetDescription()))
            return names
        except Exception as exc:
            log.get().debug("list_voices failed: %s", exc)
            return []

    def synth(self, text: str, cfg) -> "tuple[np.ndarray, int] | None":
        """Return (float mono samples, sample_rate) or None on failure."""
        from .paths import data_dir

        vcfg = cfg.get("voice", {})
        tmp = data_dir() / "tmp" / "tts.wav"
        try:
            return self._synth_to_file(
                text,
                tmp,
                voice_name=vcfg.get("sapi_voice", ""),
                pitch=int(vcfg.get("sapi_pitch", -12)),
                rate=int(vcfg.get("sapi_rate", -1)),
                volume=int(vcfg.get("sapi_volume", 100)),
            )
        except Exception:
            log.get().exception("SAPI synthesis failed")
            return None
        finally:
            try:
                if tmp.exists():
                    tmp.unlink()
            except OSError:
                pass

    # ------------------------------------------------------------ internals
    def _select_voice(self, sp, wanted: str):
        voices = sp.GetVoices()
        names = [str(voices.Item(i).GetDescription()) for i in range(voices.Count)]
        if not names:
            return None, ""
        chosen = None
        if wanted:
            for n in names:
                if wanted.lower() in n.lower():
                    chosen = n
                    break
        if chosen is None:
            for n in names:
                if any(h in n.lower() for h in _MALE_HINTS):
                    chosen = n
                    break
        if chosen is None:
            chosen = names[0]
        for i in range(voices.Count):
            if str(voices.Item(i).GetDescription()) == chosen:
                return voices.Item(i), chosen
        return None, ""

    def _synth_to_file(self, text: str, out_path: Path, voice_name: str, pitch: int, rate: int, volume: int) -> "tuple[np.ndarray, int]":
        import pythoncom
        import win32com.client

        pythoncom.CoInitialize()
        sp = win32com.client.Dispatch("SAPI.SpVoice")
        voice, desc = self._select_voice(sp, voice_name)
        if voice is not None:
            sp.Voice = voice
            self._voice_desc = desc

        stream = win32com.client.Dispatch("SAPI.SpFileStream")
        try:
            fmt = win32com.client.Dispatch("SAPI.SpAudioFormat")
            fmt.Type = 19  # SAFT22kHz16BitMono
            stream.Format = fmt
        except Exception:
            log.get().debug("could not set SpAudioFormat; using default")

        if out_path.exists():
            out_path.unlink()
        stream.Open(str(out_path))  # default mode: create-for-write
        sp.AudioOutputStream = stream

        xml = (
            f'<volume level="{max(0, min(100, volume))}">'
            f'<rate absspeed="{max(-10, min(10, rate))}">'
            f'<pitch middle="{max(-50, min(50, pitch))}">'
            f"{_escape_sapi(text)}"
            "</pitch></rate></volume>"
        )
        sp.Speak(xml, 8)  # SVSFIsXML, synchronous
        stream.Close()

        return _read_wav_mono(out_path)


def _read_wav_mono(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as wf:
        sr = wf.getframerate()
        nch = wf.getnchannels()
        sw = wf.getsampwidth()
        raw = wf.readframes(wf.getnframes())
    if sw == 2:
        x = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    elif sw == 4:
        x = np.frombuffer(raw, dtype="<i4").astype(np.float32) / 2147483648.0
    else:  # 8-bit unsigned
        x = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    if nch > 1:
        x = x.reshape(-1, nch).mean(axis=1)
    return x, sr  # type: ignore[return-value]
