"""Minimal thread-safe event bus.

Producers call ``emit(name, data)`` from any thread; the GUI thread pumps
``dispatch()`` regularly (via ``widget.after``) which delivers events to
subscribers on the GUI thread.
"""

from __future__ import annotations

import queue
import threading
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class Event:
    name: str
    data: Any = None


class EventBus:
    def __init__(self) -> None:
        self._q: "queue.Queue[Event]" = queue.Queue()
        self._subs: dict[str, list[Callable[[Any], None]]] = {}
        self._lock = threading.Lock()

    def emit(self, name: str, data: Any = None) -> None:
        """Queue an event (safe from any thread)."""
        self._q.put(Event(name, data))

    def subscribe(self, name: str, fn: Callable[[Any], None]) -> None:
        with self._lock:
            self._subs.setdefault(name, []).append(fn)

    def dispatch(self) -> None:
        """Deliver all queued events to subscribers (call from the GUI thread)."""
        while True:
            try:
                ev = self._q.get_nowait()
            except queue.Empty:
                return
            for fn in list(self._subs.get(ev.name, ())):
                try:
                    fn(ev.data)
                except Exception:
                    from . import log

                    log.get().exception("event handler failed for %s", ev.name)
