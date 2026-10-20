"""Rolling match patterns: momentum, pressure, chaos, tempo and field tilt.

All patterns look at a sliding window of recent match time (5 minutes by default),
so they describe what is happening now rather than the whole match.

- momentum:   -1 (away on top) to +1 (home on top), from threat created (xT added + xG)
- pressure:   high pressures per minute by each team (in the opponent's half)
- chaos:      0 (calm, long spells on the ball) to 1 (frantic, possession changing constantly)
- tempo:      passes per minute, both teams
- field_tilt: each team's share of passes in the final third
"""

from __future__ import annotations

from collections import deque
from typing import Callable

WINDOW_S = 300.0


class Patterns:
    def __init__(self, home: str, away: str, window_s: float = WINDOW_S):
        self.home, self.away = home, away
        self.window = window_s
        self.items: deque[tuple[float, str, str, float]] = deque()  # (time, kind, team, value)
        self.now = 0.0
        self.momentum_series: list[dict] = []
        self._last_minute = -1
        self._ema = 0.0

    def add(self, now: float, kind: str, team: str | None, value: float = 1.0):
        self.items.append((now, kind, team or "", value))

    def advance(self, now: float, label: Callable[[float], tuple[int, int]] | None = None):
        """Move the window to match time `now` (seconds since kick-off, without the half-time break).

        `label` turns a match time into (period, broadcast minute) for the momentum series,
        so second-half points line up with the match clock whatever the first-half stoppage time.
        """
        self.now = now
        while self.items and self.items[0][0] < now - self.window:
            self.items.popleft()
        tick = int(now // 60)
        while self._last_minute < tick:
            self._last_minute += 1
            self._ema = 0.6 * self._ema + 0.4 * self.momentum_raw()
            period, minute = label(self._last_minute * 60) if label else (1, self._last_minute)
            cap = 45 if period == 1 else 90
            clock = f"{cap}+{minute - cap}'" if minute > cap else f"{minute}'"
            self.momentum_series.append({"period": period, "minute": minute, "clock": clock,
                                         "value": round(self._ema * 100)})

    def _sum(self, kind: str, team: str | None = None) -> float:
        return sum(v for _, k, t, v in self.items if k == kind and (team is None or t == team))

    def _span_min(self) -> float:
        return max(1.0, min(self.window, self.now) / 60)

    def momentum_raw(self) -> float:
        """Momentum over the window right now, without smoothing."""
        h, a = self._sum("threat", self.home), self._sum("threat", self.away)
        return (h - a) / (h + a + 0.05)  # the small constant keeps quiet spells near 0

    @property
    def momentum(self) -> float:
        """Momentum smoothed minute by minute (what the momentum chart shows)."""
        return self._ema

    def current(self) -> dict:
        span = self._span_min()
        changes = self._sum("possession_change") / span
        ft_h, ft_a = self._sum("final_third_pass", self.home), self._sum("final_third_pass", self.away)
        return {
            "window_minutes": round(span, 1),
            "momentum": round(self._ema, 3),
            "momentum_raw": round(self.momentum_raw(), 3),
            "pressure": {self.home: round(self._sum("high_pressure", self.home) / span, 2),
                         self.away: round(self._sum("high_pressure", self.away) / span, 2)},
            "chaos": round(max(0.0, min(1.0, (changes - 1.5) / 3.0)), 3),
            "possession_changes_per_min": round(changes, 2),
            "tempo": round(self._sum("pass") / span, 1),
            "field_tilt": {self.home: round(ft_h / (ft_h + ft_a), 3) if ft_h + ft_a else 0.5,
                           self.away: round(ft_a / (ft_h + ft_a), 3) if ft_h + ft_a else 0.5},
        }
