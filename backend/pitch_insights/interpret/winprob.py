"""Live win probability from the score, time left, chance quality so far and red cards.

Each team's goal rate for the rest of the match blends a prior (league average,
adjusted for league position and home advantage) with its xG rate in this match.
The remaining goals for each side are treated as Poisson, which gives the chances
of each final result.
"""

from __future__ import annotations

import math

LEAGUE_GOALS_PER_TEAM = 1.35  # per 90 minutes
PRIOR_WEIGHT_MIN = 45.0       # the prior counts as this many minutes of evidence
FULL_TIME_MIN = 93.0          # typical end including stoppage time


def _poisson(lam: float, k: int) -> float:
    return math.exp(-lam) * lam ** k / math.factorial(k)


def prior_rate(league_position: int, is_home: bool) -> float:
    """Goals per minute before the match starts."""
    strength = 1 + (10.5 - league_position) * 0.035
    return LEAGUE_GOALS_PER_TEAM * strength * (1.12 if is_home else 0.9) / 90


def win_probability(score_home: int, score_away: int, minute: float,
                    xg_home: float, xg_away: float,
                    prior_home: float, prior_away: float,
                    men_home: int = 11, men_away: int = 11,
                    finished: bool = False) -> dict:
    if finished:
        if score_home > score_away:
            return {"home": 1.0, "draw": 0.0, "away": 0.0}
        if score_home < score_away:
            return {"home": 0.0, "draw": 0.0, "away": 1.0}
        return {"home": 0.0, "draw": 1.0, "away": 0.0}
    played = max(minute, 0.0)
    rate_h = (prior_home * PRIOR_WEIGHT_MIN + xg_home) / (PRIOR_WEIGHT_MIN + played)
    rate_a = (prior_away * PRIOR_WEIGHT_MIN + xg_away) / (PRIOR_WEIGHT_MIN + played)
    diff = men_home - men_away  # each extra man is worth about 30% more goals
    rate_h *= 1.3 ** diff
    rate_a *= 1.3 ** (-diff)
    left = max(0.0, max(FULL_TIME_MIN, minute + 1) - minute)
    lam_h, lam_a = rate_h * left, rate_a * left
    ph = [_poisson(lam_h, k) for k in range(11)]
    pa = [_poisson(lam_a, k) for k in range(11)]
    home = draw = away = 0.0
    for i, p_i in enumerate(ph):
        for j, p_j in enumerate(pa):
            fh, fa = score_home + i, score_away + j
            p = p_i * p_j
            if fh > fa:
                home += p
            elif fh == fa:
                draw += p
            else:
                away += p
    total = home + draw + away
    return {"home": round(home / total, 4), "draw": round(draw / total, 4), "away": round(away / total, 4)}
