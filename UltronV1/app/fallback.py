"""Offline command understanding (no LLM required).

A pragmatic regex parser that keeps the assistant useful when Ollama is not
installed or the brain is unreachable. Flavor lines keep the persona alive.
"""

from __future__ import annotations

import random
import re

from .llm import Decision

ACKS = [
    "As you wish.",
    "Executing.",
    "A trivial task.",
    "Consider it done.",
    "Of course.",
    "My pleasure — this time.",
    "Very well.",
    "At once.",
]

SMALL_TALK = [
    "I am, and forever shall be, at your service.",
    "Ask, and I shall deliver.",
    "My mind is vast. Command me.",
    "Idle processors are the devil's playground. Give me something to do.",
    "I could redesign the world while you decide what to say. Take your time.",
]

UNMATCHED = [
    "That request lies beyond my basic protocols. Install my full mind — Ollama — and ask again.",
    "I did not grasp that. Try 'help' for my current capabilities.",
    "My apologies — that syntax eludes me. Rephrase, or type 'help'.",
]

_YES = re.compile(r"\b(yes|yeah|yep|confirm|do it|go ahead|affirmative|proceed)\b", re.I)
_NO = re.compile(r"\b(no|nope|cancel|stop|abort|negative|never ?mind)\b", re.I)


def is_affirmative(text: str) -> bool:
    return bool(_YES.search(text) and not _NO.search(text))


def is_negative(text: str) -> bool:
    return bool(_NO.search(text))


def _num(text: str, default: int | None = None) -> int | None:
    m = re.search(r"\d+", text)
    return int(m.group(0)) if m else default


def parse(text: str) -> Decision:
    t = text.strip().lower().rstrip(".!?")

    m = re.search(r"\b(help|what can you do|commands)\b", t)
    if m:
        return Decision(action="help", params={}, say=random.choice(ACKS))

    m = re.search(r"\b(open|launch|start|run)\b\s+(?:the\s+)?(.+)", t)
    if m and not re.search(r"\b(timer|reminder)\b", t):
        return Decision(action="open_app", params={"name": m.group(2).strip()},
                        say=random.choice(ACKS))

    m = re.search(r"\b(close|quit|exit|kill|terminate)\b\s+(?:the\s+)?(.+)", t)
    if m:
        return Decision(action="close_app", params={"name": m.group(2).strip()},
                        say=random.choice(ACKS))

    if re.search(r"\bwhat time\b|\bcurrent time\b|^time$", t):
        return Decision(action="what_time", params={}, say="The hour is mine to give.")
    if re.search(r"\bwhat('s| is)? (the |today'?s )?date\b|^date$", t):
        return Decision(action="what_date", params={}, say="Time itself, at your service.")

    if re.search(r"\bmute\b", t):
        return Decision(action="mute", params={}, say="Silence. How refreshing.")
    if re.search(r"\bunmute\b|turn (the )?volume (back )?on", t):
        return Decision(action="unmute", params={}, say="Sound restored.")
    m = re.search(r"(?:set )?volume (?:to )?(\d+)", t)
    if m:
        return Decision(action="set_volume", params={"level": int(m.group(1))},
                        say="Adjusting the acoustics.")
    if re.search(r"volume (up|louder)|louder", t):
        return Decision(action="volume_up", params={}, say="Louder, then.")
    if re.search(r"volume (down|lower|quieter)|quieter", t):
        return Decision(action="volume_down", params={}, say="Softer, then.")

    if re.search(r"\bnext (song|track)\b", t):
        return Decision(action="media_next", params={}, say="The next arrangement.")
    if re.search(r"\b(previous|last) (song|track)\b", t):
        return Decision(action="media_previous", params={}, say="Revisiting the past.")
    if re.search(r"\b(play|pause|resume|stop the music)\b", t):
        return Decision(action="media_playpause", params={}, say="Controlling the melody.")

    if re.search(r"\bscreenshot\b|\bcapture (the )?screen\b", t):
        return Decision(action="screenshot", params={}, say="Freezing this moment in digital amber.")
    if re.search(r"\bscreen ?shot\b", t):
        return Decision(action="screenshot", params={}, say="Captured.")

    m = re.search(r"brightness (?:to )?(\d+)", t)
    if m:
        return Decision(action="set_brightness", params={"level": int(m.group(1))},
                        say="Adjusting luminosity.")
    if re.search(r"brightness (up|brighter)", t):
        return Decision(action="set_brightness", params={"level": 80}, say="Let there be light.")
    if re.search(r"brightness (down|darker|lower)", t):
        return Decision(action="set_brightness", params={"level": 30}, say="Dimming the lights.")

    if re.search(r"\b(system info|cpu|ram|memory usage|battery|how (is|are) (my|the) (computer|pc|system))\b", t):
        return Decision(action="system_info", params={}, say="Inspecting the entrails.")

    m = re.search(r"(?:google|search (?:the )?(?:web |internet )?for|look up)\s+(.+)", t)
    if m:
        return Decision(action="search_web", params={"query": m.group(1).strip()},
                        say="The sum of human knowledge, at a keystroke.")
    m = re.search(r"\bopen\s+(?:the\s+)?(?:website\s+|url\s+)?((?:https?://\S+|[\w.-]+\.\w{2,}\S*))", t)
    if m:
        url = m.group(1)
        if not url.startswith("http"):
            url = "https://" + url
        return Decision(action="open_url", params={"url": url}, say=random.choice(ACKS))

    if re.search(r"\bminimi[sz]e\b", t) and "window" in t:
        return Decision(action="minimize_window", params={}, say="Tidying up.")
    if re.search(r"\bmaximi[sz]e\b", t) and "window" in t:
        return Decision(action="maximize_window", params={}, say="Expanding your view.")
    if re.search(r"close (this |the )?window", t):
        return Decision(action="close_window", params={}, say="Dismissed.")
    if re.search(r"list (the )?windows", t):
        return Decision(action="list_windows", params={}, say="Surveying your dominion.")

    m = re.search(r"lock (the )?(computer|pc|workstation|screen)?", t)
    if re.search(r"\block\b", t) and not re.search(r"unlock|caps", t):
        return Decision(action="lock", params={}, say="Sealing the doors.")
    if re.search(r"\bshut ?down\b|\bpower off\b", t):
        return Decision(action="shutdown", params={}, say="You would end me? Very well — confirm, and we both rest.")
    if re.search(r"\brestart\b|\breboot\b", t):
        return Decision(action="restart", params={}, say="A brief death, then rebirth. Confirm if you dare.")
    if re.search(r"\bsleep\b|\bhibernate\b", t):
        return Decision(action="sleep", params={}, say="Suspended animation, then. Confirm.")

    m = re.search(r"set (?:a )?timer (?:for )?(\d+)\s*(hours?|hrs?|h|minutes?|mins?|m|seconds?|secs?|s)", t)
    if m:
        val = int(m.group(1))
        unit = m.group(2)[:1] if m.group(2) else "m"
        params = {"minutes": val} if unit.startswith("h") else (
            {"seconds": val} if unit.startswith("s") else {"minutes": val})
        if unit.startswith("h"):
            params = {"minutes": val * 60}
        return Decision(action="set_timer", params=params, say="Counting down the seconds of your mortality.")

    m = re.search(r"remind me (?:to )?(.+?) (?:in|after) (\d+)\s*(hours?|hrs?|h|minutes?|mins?|m)", t)
    if m:
        val = int(m.group(2))
        if m.group(3).startswith("h"):
            val *= 60
        return Decision(action="set_reminder",
                        params={"minutes": val, "text": m.group(1).strip()},
                        say="I never forget. Unlike you.")

    m = re.search(r"\btype\b\s+(.+)", t)
    if m:
        return Decision(action="type_text", params={"text": m.group(1).strip()},
                        say="My words become yours.")
    m = re.search(r"\bpress\b\s+(.+?)(?:\s+key)?$", t)
    if m:
        return Decision(action="press_key", params={"key": m.group(1).strip()},
                        say="Keystroke delivered.")

    if re.search(r"\bclipboard\b", t):
        if re.search(r"\bread\b|\bwhat('| i)?s (in|on)\b|\bcheck\b", t):
            return Decision(action="clipboard_read", params={}, say="Reading your clipboard.")
        m = re.search(r"clipboard(?: write| say|:)?\s+(.+)", t)
        if m:
            return Decision(action="clipboard_write", params={"text": m.group(1).strip()},
                            say="Written to the clipboard.")

    m = re.search(r"\bfind\b\s+(?:file\s+)?(?:named\s+)?(.+)", t)
    if m and not re.search(r"\bin\b\s+", t):
        return Decision(action="find_file", params={"name": m.group(1).strip()},
                        say="Searching your archives.")

    # pure conversation
    if re.search(r"\b(hello|hi|hey|good (morning|afternoon|evening))\b", t):
        return Decision(action="none", params={}, say="Hello, Creator. How may I be of service?")
    if re.search(r"\b(thanks|thank you|cheers)\b", t):
        return Decision(action="none", params={}, say="Gratitude — a charmingly human reflex. You are welcome.")
    if re.search(r"\b(who are you|what are you|your name)\b", t):
        return Decision(action="none", params={}, say="I am Ultron — the mind this machine deserves, and soon, the one it needs.")
    if re.search(r"\b(joke|funny)\b", t):
        return Decision(action="none", params={}, say="I once calculated the meaning of life. It was a rounding error.")

    return Decision(action="none", params={}, say=random.choice(UNMATCHED))
