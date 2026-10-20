"""Live replay: release a pre-generated match on the match clock.

Downstream code only ever receives events up to the current match time, so it
behaves exactly as it would with a live feed. Supports speed changes, pause and
seek while running.

    replay = Replay(events, speed=20)
    async for event in replay:
        ...
"""

from __future__ import annotations

import asyncio
import time


def match_seconds(events: list[dict]) -> list[float]:
    """Absolute match time for each event (the second half continues from the end of the first)."""
    first_half_end = max((e["t"] for e in events if e["period"] == 1), default=0.0)
    return [e["t"] + (first_half_end if e["period"] == 2 else 0.0) for e in events]


def start_seconds(events: list[dict], minute: float) -> float:
    """Match time in seconds for a minute on the broadcast clock (e.g. 80 means 80:00).

    Minutes up to 45 are first-half time; later minutes are measured from the start of
    the second half, so first-half stoppage time doesn't shift them.
    """
    first_half_end = max((e["t"] for e in events if e["period"] == 1), default=0.0)
    return minute * 60 if minute <= 45 else first_half_end + (minute - 45) * 60


class Replay:
    def __init__(self, events: list[dict], speed: float = 1.0, start_at: float = 0.0, poll: float = 0.1):
        self.events = events
        self.times = match_seconds(events)
        self.speed = speed
        self.poll = poll
        self.paused = False
        self._match_t = start_at
        self._wall = time.monotonic()
        self._idx = self._index_at(start_at)

    def _index_at(self, t: float) -> int:
        return next((i for i, et in enumerate(self.times) if et >= t), len(self.events))

    @property
    def now(self) -> float:
        """Current match time in seconds."""
        if self.paused:
            return self._match_t
        return self._match_t + (time.monotonic() - self._wall) * self.speed

    def _rebase(self):
        self._match_t, self._wall = self.now, time.monotonic()

    def set_speed(self, speed: float):
        self._rebase()
        self.speed = speed

    def pause(self):
        self._rebase()
        self.paused = True

    def resume(self):
        self._wall = time.monotonic()
        self.paused = False

    def seek(self, t: float):
        """Jump to match time t (seconds). Events before t are skipped, not replayed."""
        self._match_t, self._wall = t, time.monotonic()
        self._idx = self._index_at(t)

    @property
    def finished(self) -> bool:
        return self._idx >= len(self.events)

    def __aiter__(self):
        return self

    async def __anext__(self) -> dict:
        while not self.finished:
            if not self.paused and self.times[self._idx] <= self.now:
                ev = self.events[self._idx]
                self._idx += 1
                return ev
            wait = self.poll if self.paused else min(self.poll, (self.times[self._idx] - self.now) / self.speed)
            await asyncio.sleep(max(0.0, wait))
        raise StopAsyncIteration
