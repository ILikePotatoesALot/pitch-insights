"""Live player ratings (3.0-10.0, everyone starts at 6.0) with a breakdown of every change.

Each event adds or subtracts points for the players involved. Points are weighted
by position (defenders earn more for defending, attackers for attacking), and the
shown rating is damped by playing time, so one good touch in three minutes can't
send a substitute to 8.5. Every contribution is kept, so the UI can show exactly
why a rating is what it is.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

BASE = 6.0
DAMPING_MIN = 15.0   # rating moves = raw * minutes / (minutes + DAMPING_MIN)
SCALE = 1.15         # overall scale, tuned with scripts/calibrate_ratings.py
KNEE = 1.8           # above 6.0 + KNEE, extra points count for less (diminishing returns)
KNEE_SLOPE = 0.5

GROUP = {"GK": "GK", "CB": "DEF", "FB": "DEF", "DM": "MID", "CM": "MID", "AM": "MID", "W": "ATT", "ST": "ATT"}

# Multipliers per position group for each category of contribution. Each position
# makes very different numbers of actions (midfielders pass and press far more than
# centre-backs), so these bring every position to a similar average, about 6.8, while
# rewarding what that position is for. Goals and assists count fully for everyone.
# Tuned with scripts/calibrate_ratings.py.
WEIGHTS = {
    "GK":  {"attacking": 1.0, "goals": 1.0, "passing": 1.0, "defending": 1.0, "goalkeeping": 1.2, "discipline": 1.0, "errors": 0.3, "conceding": 0.8},
    "DEF": {"attacking": 0.6, "goals": 1.0, "passing": 1.8, "defending": 4.8, "goalkeeping": 1.0, "discipline": 0.7, "errors": 0.4, "conceding": 1.0},
    "MID": {"attacking": 0.21, "goals": 1.0, "passing": 0.24, "defending": 0.2, "goalkeeping": 1.0, "discipline": 0.45, "errors": 0.3, "conceding": 0.25},
    "ATT": {"attacking": 0.35, "goals": 1.0, "passing": 0.24, "defending": 0.15, "goalkeeping": 1.0, "discipline": 0.5, "errors": 0.6, "conceding": 0.0},
}

CATEGORY_LABEL = {
    "attacking": "Attacking", "goals": "Goals and assists", "passing": "Passing", "defending": "Defending", "goalkeeping": "Goalkeeping",
    "discipline": "Discipline", "errors": "Errors", "conceding": "Goals conceded",
}


@dataclass(frozen=True)
class Contribution:
    seq: int
    clock: str
    category: str
    label: str
    delta: float  # after position weighting, before playing-time damping


class Ratings:
    def __init__(self, positions: dict[str, str]):
        self.group = {pid: GROUP[pos] for pid, pos in positions.items()}
        self.raw: dict[str, float] = defaultdict(float)
        self.log: dict[str, list[Contribution]] = defaultdict(list)
        self.changed: set[str] = set()  # players whose points changed since the last pop_changed()

    def add(self, pid: str, seq: int, clock: str, category: str, label: str, points: float):
        if not pid or pid not in self.group:
            return
        delta = points * WEIGHTS[self.group[pid]][category] * SCALE
        if delta == 0:
            return
        self.raw[pid] += delta
        self.log[pid].append(Contribution(seq, clock, category, label, round(delta, 4)))
        self.changed.add(pid)

    def pop_changed(self) -> set[str]:
        changed, self.changed = self.changed, set()
        return changed

    def _shown_points(self, pid: str, minutes: float) -> tuple[float, float]:
        """(points before damping and the knee, points actually shown above 6.0)."""
        raw = self.raw[pid]
        damp = minutes / (minutes + DAMPING_MIN) if minutes > 0 else 0.0
        x = raw * damp
        if x > KNEE:
            x = KNEE + (x - KNEE) * KNEE_SLOPE
        return raw, max(3.0 - BASE, min(10.0 - BASE, x))

    def rating(self, pid: str, minutes: float) -> float:
        return round(BASE + self._shown_points(pid, minutes)[1], 1)

    def breakdown(self, pid: str, minutes: float, top: int = 5) -> dict:
        """Rating, the points per category and the biggest single contributions.

        Category totals and moments are scaled by the same factor as the rating
        (playing-time damping, diminishing returns and the 3-10 limits), so they
        add up to the rating minus 6.0.
        """
        raw, shown = self._shown_points(pid, minutes)
        scale = shown / raw if raw else 0.0
        totals: dict[str, float] = defaultdict(float)
        for c in self.log[pid]:
            totals[c.category] += c.delta
        biggest = sorted(self.log[pid], key=lambda c: -abs(c.delta))[:top]
        return {
            "rating": self.rating(pid, minutes),
            "by_category": {CATEGORY_LABEL[k]: round(v * scale, 2) for k, v in
                            sorted(totals.items(), key=lambda kv: -abs(kv[1])) if abs(v * scale) >= 0.01},
            "key_moments": [{"clock": c.clock, "label": c.label, "delta": round(c.delta * scale, 2), "seq": c.seq}
                            for c in biggest],
            "scale": round(scale, 3),
        }
