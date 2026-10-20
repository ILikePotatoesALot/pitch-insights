"""Shot quality (expected goals) from location, body part and pressure."""

import math

GOAL_X, GOAL_Y, GOAL_HALF_WIDTH = 105.0, 34.0, 3.66


def distance_to_goal(x: float, y: float) -> float:
    return math.hypot(GOAL_X - x, GOAL_Y - y)


def goal_angle(x: float, y: float) -> float:
    """Angle in radians the goal mouth covers, seen from (x, y)."""
    dx = max(GOAL_X - x, 0.1)
    a1 = math.atan2(GOAL_Y + GOAL_HALF_WIDTH - y, dx)
    a2 = math.atan2(GOAL_Y - GOAL_HALF_WIDTH - y, dx)
    return abs(a1 - a2)


def expected_goals(x: float, y: float, header: bool = False, under_pressure: bool = False,
                   kind: str = "open_play") -> float:
    if kind == "penalty":
        return 0.78
    d, a = distance_to_goal(x, y), goal_angle(x, y)
    logit = -0.9 - 0.10 * d + 1.0 * a
    if header:
        logit -= 1.0
    if under_pressure:
        logit -= 0.3
    if kind == "free_kick":
        logit -= 0.2
    return round(min(0.95, max(0.01, 1 / (1 + math.exp(-logit)))), 3)
