"""Functional test suite (no pytest required). Run: python scripts/test_functional.py

Covers: the ULTRON voice DSP chain, the offline command parser, the
executor, the Ollama JSON parser, and the full assistant service
pipeline including the power-command confirmation flow.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np


def test_fx() -> None:
    from app import fx

    sr = 22050
    t = np.arange(int(sr * 1.5)) / sr
    f0 = 120 + 30 * np.sin(2 * np.pi * 3 * t)
    phase = 2 * np.pi * np.cumsum(f0) / sr
    speech = (
        0.6 * np.sin(phase)
        + 0.3 * np.sin(2 * phase)
        + 0.15 * np.sin(3 * phase)
        + 0.05 * np.random.default_rng(1).standard_normal(len(t))
    )
    env = np.clip(np.abs(np.sin(2 * np.pi * 2.5 * t)) ** 0.5, 0.05, 1.0)
    speech = speech * env

    out = fx.ultronize(speech, sr, intensity=1.0, extra_pitch_semitones=2.5)
    assert out.ndim == 1
    assert len(out) > len(speech), "expected longer output (pitch-down)"
    assert np.all(np.isfinite(out)), "non-finite samples"
    assert np.max(np.abs(out)) <= 1.0, "clipping"
    assert np.max(np.abs(out)) > 0.5, "too quiet / empty"

    out0 = fx.ultronize(speech, sr, intensity=0.0, extra_pitch_semitones=0.0)
    assert np.all(np.isfinite(out0))
    print("fx.ultronize OK")


def test_fallback() -> None:
    from app import fallback

    cases = {
        "open notepad": "open_app",
        "launch google chrome": "open_app",
        "close spotify": "close_app",
        "what time is it": "what_time",
        "set volume to 40": "set_volume",
        "mute": "mute",
        "next song": "media_next",
        "take a screenshot": "screenshot",
        "set brightness to 70": "set_brightness",
        "what's my cpu usage": "system_info",
        "google the weather in rome": "search_web",
        "shut down the computer": "shutdown",
        "set a timer for 5 minutes": "set_timer",
        "remind me to stretch in 30 minutes": "set_reminder",
        "type hello world": "type_text",
        "press enter": "press_key",
        "help": "help",
        "lock the pc": "lock",
    }
    for text, want in cases.items():
        d = fallback.parse(text)
        assert d.action == want, f"{text!r}: {d.action!r} != {want!r}"
        assert d.say, f"{text!r}: empty reply"
    assert fallback.is_affirmative("yes do it") and not fallback.is_affirmative("no")
    assert fallback.is_negative("never mind") and not fallback.is_negative("yes")
    print(f"fallback.parse OK: {len(cases)} patterns")


def test_llm_parse() -> None:
    from app.llm import OllamaBrain

    d = OllamaBrain._parse('{"action":"open_app","params":{"name":"notepad"},"say":"Behold."}')
    assert d.action == "open_app" and d.params["name"] == "notepad"
    d = OllamaBrain._parse('```json\n{"action":"none","params":{},"say":"Hi."}\n```')
    assert d.action == "none"
    d = OllamaBrain._parse('Sure! {"action":"set_volume","params":{"level":40},"say":"Done."} ok')
    assert d.action == "set_volume" and d.params["level"] == 40
    assert OllamaBrain._parse('{"action":"screenshot","params":{}}').say == "Done."
    assert OllamaBrain._parse('{"action":"open_app","params":"x","say":"ok"}').params == {}
    assert OllamaBrain._parse("no json") is None
    assert OllamaBrain._parse("") is None
    assert OllamaBrain._parse("[1,2]") is None
    print("OllamaBrain._parse OK")


def test_executor() -> None:
    from app.commands.executor import Executor
    from app.config import Config

    ex = Executor(Config(), speak=None)
    assert ex.run("what_time", {}).ok
    assert ex.run("what_date", {}).ok
    assert "shut down" in ex.run("help", {}).detail.lower()
    assert ex.run("set_timer", {"minutes": 0.01}).ok
    assert not ex.run("bogus_action", {}).ok
    assert not ex.run("set_volume", {"level": "NaN"}).ok
    print("executor OK")


def test_service() -> None:
    from app.bus import EventBus
    from app.config import Config
    from app.service import AssistantService

    bus = EventBus()
    svc = AssistantService(Config(), bus)
    svc.start()
    time.sleep(0.4)

    replies: list[str] = []
    bus.subscribe("reply", replies.append)

    def drain(want: int, timeout_s: float = 8.0) -> None:
        deadline = time.monotonic() + timeout_s
        while len(replies) < want and time.monotonic() < deadline:
            bus.dispatch()
            time.sleep(0.05)
        bus.dispatch()

    svc.submit_text("what time is it")
    svc.submit_text("hello ultron")
    drain(2)
    assert len(replies) >= 2, replies
    assert any("It is" in r or "hour" in r for r in replies), replies

    # power actions require confirmation
    svc.submit_text("shut down the computer")
    drain(3)
    assert any("confirm" in r.lower() for r in replies), replies

    svc.submit_text("no")
    drain(4)
    assert any("cancel" in r.lower() for r in replies), replies

    svc.shutdown()
    print("service pipeline + confirmation flow OK")


def test_custom_commands() -> None:
    from app.custom_commands import (
        match_custom_command,
        normalize,
        parse_params_block,
        score,
    )

    assert normalize("What's the Time?") == "whats the time"
    assert normalize("  Ultron,  OPEN—notepad!! ") == "ultron open notepad"

    # wake-word calibration: mishearings high, chit-chat low
    assert score("altron open notepad", "ultron") >= 0.75
    assert score("ultra on", "ultron") >= 0.75
    assert score("ultrahn", "ultron") >= 0.75
    assert score("hey ultron", "ultron") == 1.0
    assert score("turn on the lights", "ultron") < 0.65
    assert score("what time is it", "ultron") < 0.4

    commands = [
        {"id": "cc-1", "name": "Workspace", "phrases": ["open my workspace", "open my work space"],
         "action": "open_app", "params": {"name": "chrome"}, "reply": "Your domain.", "enabled": True},
        {"id": "cc-2", "name": "Disabled", "phrases": ["open my workspace"],
         "action": "open_app", "params": {}, "reply": "", "enabled": False},
        {"id": "cc-3", "name": "FocusMode", "phrases": ["focus mode on"],
         "action": "set_volume", "params": {"level": "10"}, "reply": "Focus.", "enabled": True},
    ]
    m = match_custom_command("open my workspace", commands)
    assert m and m[0]["name"] == "Workspace"
    m = match_custom_command("open my work space please", commands)
    assert m and m[0]["name"] == "Workspace"
    m = match_custom_command("focus mode on", commands)
    assert m and m[0]["name"] == "FocusMode" and m[0]["params"]["level"] == "10"
    assert match_custom_command("close my workspace", [{"id": "x", "phrases": ["zzz unrelated"],
        "action": "open_app", "enabled": True}]) is None
    assert match_custom_command("what time is it", commands) is None

    assert parse_params_block("name = chrome\nlevel: 40\n# comment\n") == {
        "name": "chrome", "level": "40"}
    print("custom_commands OK")


def test_wake_matching() -> None:
    from app.bus import EventBus
    from app.config import Config
    from app.service import AssistantService

    cfg = Config()
    cfg.set("wake.variants", ["altron", "ultra on"])
    svc = AssistantService(cfg, EventBus())

    assert svc.matches_wake("ultron")
    assert svc.matches_wake("ultron open notepad")
    assert svc.matches_wake("altron open notepad")     # trained variant
    assert svc.matches_wake("ultra on")                # trained variant
    assert svc.matches_wake("oltron")                  # fuzzy
    assert not svc.matches_wake("what time is it")
    assert not svc.matches_wake("turn on the lights")
    assert not svc.matches_wake("")

    variants = svc._wake_variants()
    assert "ultron" in variants and "altron" in variants
    print("wake matching OK (trained variants + fuzzy)")


def test_custom_command_flow() -> None:
    from app.bus import EventBus
    from app.config import Config
    from app.service import AssistantService

    cfg = Config()
    cfg.set("custom_commands", [{
        "id": "cc-t", "name": "TimePlease", "phrases": ["whats the time mr robot"],
        "action": "what_time", "params": {}, "reply": "Make it so.", "enabled": True,
    }])
    bus = EventBus()
    svc = AssistantService(cfg, bus)
    svc.start()
    time.sleep(0.4)

    replies, matches = [], []
    bus.subscribe("reply", replies.append)
    bus.subscribe("custom_match", matches.append)

    deadline = time.monotonic() + 8
    svc.submit_text("whats the time mr robot")
    while time.monotonic() < deadline and not replies:
        bus.dispatch()
        time.sleep(0.05)
    bus.dispatch()

    assert matches and matches[0]["name"] == "TimePlease", matches
    assert replies and "Make it so" in replies[0], replies
    assert "It is" in replies[0], replies

    svc.shutdown()
    print("custom command flow OK (trained phrase -> action -> reply)")


def main() -> int:
    test_fx()
    test_fallback()
    test_llm_parse()
    test_executor()
    test_custom_commands()
    test_wake_matching()
    test_service()
    test_custom_command_flow()
    print("ALL FUNCTIONAL TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
