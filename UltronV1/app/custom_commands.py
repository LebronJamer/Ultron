"""Phrase matching for trained wake words and custom commands.

Vosk is a static acoustic model — it cannot be acoustically fine-tuned per
user on the fly. What we *can* do (and what makes training effective) is:

1. collect what Vosk actually hears when THIS user says the phrase on THIS
   microphone (the "variants"), and
2. match incoming transcripts against those variants fuzzily, so
   'altron', 'ultr on' and 'ultra on' all still wake him up.

This module holds the pure matching logic so it is trivially testable.
"""

from __future__ import annotations

import difflib
import unicodedata


def normalize(text: str) -> str:
    """Lowercase, strip punctuation/accents, collapse whitespace.

    Unicode punctuation (em dashes, curly quotes…) becomes a SPACE, never
    deleted — otherwise 'open—notepad' would glue into 'opennotepad'.
    """
    if not text:
        return ""
    t = unicodedata.normalize("NFKD", str(text))
    t = "".join(c for c in t if not unicodedata.combining(c))    # strip accents
    t = t.replace("'", "").replace("\u2019", "")                 # contractions glue: what's -> whats
    t = "".join(c if (c.isalnum() or c.isspace()) else " " for c in t)
    t = t.encode("ascii", "ignore").decode().lower()
    return " ".join(t.split())


def score(text: str, phrase: str) -> float:
    """How well does ``text`` contain/ resemble ``phrase``? 0..1.

    * exact substring                      -> 1.0
    * every word of the phrase present     -> 0.98
    * best fuzzy ratio over token windows  -> ratio
    """
    t = normalize(text)
    p = normalize(phrase)
    if not t or not p:
        return 0.0
    if p in t:
        return 1.0

    t_tokens = t.split()
    p_tokens = p.split()
    if p_tokens and all(w in t_tokens for w in p_tokens):
        return 0.98

    best = difflib.SequenceMatcher(None, p, t).ratio()
    width = len(p_tokens)
    if width <= len(t_tokens):
        for i in range(0, len(t_tokens) - width + 1):
            window = " ".join(t_tokens[i : i + width])
            r = difflib.SequenceMatcher(None, p, window).ratio()
            if r > best:
                best = r
    return best


def fuzzy_phrase_in(text: str, phrase: str, threshold: float = 0.75) -> bool:
    return score(text, phrase) >= threshold


def match_custom_command(
    text: str, commands: list, threshold: float = 0.78
):
    """Best-matching enabled custom command for ``text``.

    Returns ``(command_dict, matched_phrase, score)`` or None.
    """
    best = None  # (sc, command, phrase)
    for cc in commands or []:
        if not isinstance(cc, dict) or not cc.get("enabled", True):
            continue
        action = str(cc.get("action", "") or "").strip()
        if not action:
            continue
        for phrase in cc.get("phrases", []) or []:
            sc = score(text, str(phrase))
            if sc >= threshold and (best is None or sc > best[0]):
                best = (sc, cc, str(phrase))
    if best is None:
        return None
    return best[1], best[2], best[0]


def parse_params_block(text: str) -> dict:
    """Parse a 'key = value' / 'key: value' block (one per line)."""
    out: dict[str, str] = {}
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        for sep in ("=", ":"):
            if sep in line:
                key, _, val = line.partition(sep)
                key = key.strip()
                val = val.strip()
                if key:
                    out[key] = val
                break
    return out


def new_command_id() -> str:
    import time

    return f"cc-{int(time.time() * 1000) % 10_000_000_000}"
