"""Expected threat (xT): how likely possession in each zone is to lead to a goal.

The pitch is split into a 12 x 8 grid. Values are learned from match events with
the standard Markov method (Singh, 2018): each zone's value is the chance of
scoring by shooting from it, plus the chance of moving the ball on successfully,
weighted by the value of where it goes. `scripts/build_xt.py` learns the grid from
generated matches and writes xt_grid.json; the same script could learn it from
real data instead.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from pitch_insights.events.schema import PITCH_LENGTH, PITCH_WIDTH

COLS, ROWS = 12, 8
GRID_FILE = Path(__file__).with_name("xt_grid.json")


def zone(x: float, y: float) -> tuple[int, int]:
    c = min(COLS - 1, max(0, int(x / PITCH_LENGTH * COLS)))
    r = min(ROWS - 1, max(0, int(y / PITCH_WIDTH * ROWS)))
    return c, r


def learn_grid(matches: list[list[dict]], iterations: int = 30) -> list[list[float]]:
    """Learn xT values (grid[col][row]) from lists of events."""
    shots = [[0] * ROWS for _ in range(COLS)]
    goals = [[0] * ROWS for _ in range(COLS)]
    moves = [[0] * ROWS for _ in range(COLS)]
    trans = [[{} for _ in range(ROWS)] for _ in range(COLS)]
    for events in matches:
        for e in events:
            if e["type"] not in ("pass", "carry", "shot") or "x" not in e:
                continue
            c, r = zone(e["x"], e["y"])
            if e["type"] == "shot":
                if e["kind"] == "penalty":
                    continue
                shots[c][r] += 1
                goals[c][r] += e["outcome"] == "goal"
                continue
            moves[c][r] += 1
            if e["type"] == "carry" or e["outcome"] == "complete":
                dest = zone(e["end_x"], e["end_y"])
                trans[c][r][dest] = trans[c][r].get(dest, 0) + 1

    xt = [[0.0] * ROWS for _ in range(COLS)]
    for _ in range(iterations):
        new = [[0.0] * ROWS for _ in range(COLS)]
        for c in range(COLS):
            for r in range(ROWS):
                total = shots[c][r] + moves[c][r]
                if not total:
                    continue
                score = (shots[c][r] / total) * (goals[c][r] / shots[c][r] if shots[c][r] else 0.0)
                move = sum(n / moves[c][r] * xt[dc][dr] for (dc, dr), n in trans[c][r].items()) if moves[c][r] else 0.0
                new[c][r] = score + (moves[c][r] / total) * move
        xt = new
    return [[round(v, 5) for v in col] for col in xt]


@lru_cache(maxsize=1)
def grid() -> list[list[float]]:
    return json.loads(GRID_FILE.read_text(encoding="utf-8"))["grid"]


def value(x: float, y: float) -> float:
    c, r = zone(x, y)
    return grid()[c][r]


def added(x: float, y: float, end_x: float, end_y: float) -> float:
    """Threat added by moving the ball from (x, y) to (end_x, end_y)."""
    return value(end_x, end_y) - value(x, y)
