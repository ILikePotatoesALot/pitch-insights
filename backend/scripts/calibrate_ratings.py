"""Check the spread of live player ratings over many generated matches.

Targets (similar to public rating systems such as FotMob or SofaScore, for players
with 60+ minutes): average about 6.8, most players between 6 and 8, a typical
best-in-match around 8, and 9+ reserved for exceptional games.

    python scripts/calibrate_ratings.py          # 120 matches
"""

from __future__ import annotations

import argparse
import itertools
import statistics
import sys
from collections import defaultdict

from pitch_insights.generator.engine import simulate
from pitch_insights.generator.players import load_clubs
from pitch_insights.interpret.interpreter import Interpreter
from pitch_insights.interpret.ratings import GROUP

TARGETS = [
    ("Average rating (60+ min)", "mean", 6.6, 7.0),
    ("Spread (std dev)", "sd", 0.5, 0.85),
    ("Share below 6.0", "below6", 0.05, 0.2),
    ("Share 8.0 or above", "above8", 0.03, 0.12),
    ("Best in match (average)", "best", 7.9, 8.8),
    ("Share of matches with a 9.5+", "share95", 0.0, 0.15),
]


def run(n: int, start: int) -> int:
    pairs = list(itertools.permutations(sorted(load_clubs()), 2))
    ratings, best, by_group, by_cat, has95 = [], [], defaultdict(list), defaultdict(list), 0
    for i in range(n):
        meta, events, _ = simulate(start + i, *pairs[i % len(pairs)])
        it = Interpreter(meta)
        for e in events:
            it.update(e)
        snap = it.snapshot()
        match_r = []
        for p in snap["players"].values():
            if p["minutes"] >= 60:
                ratings.append(p["rating"])
                by_group[GROUP[p["position"]]].append(p["rating"])
                for cat, v in p["by_category"].items():
                    by_cat[(GROUP[p["position"]], cat)].append(v)
                match_r.append(p["rating"])
        best.append(max(match_r))
        has95 += max(match_r) >= 9.5

    stats = dict(mean=statistics.fmean(ratings), sd=statistics.pstdev(ratings),
                 below6=sum(r < 6.0 for r in ratings) / len(ratings),
                 above8=sum(r >= 8.0 for r in ratings) / len(ratings),
                 best=statistics.fmean(best), share95=has95 / n)
    failed = 0
    print(f"{n} matches, {len(ratings)} player ratings (60+ minutes)\n")
    for label, key, lo, hi in TARGETS:
        ok = lo <= stats[key] <= hi
        failed += not ok
        print(f"{label:<32}{stats[key]:>8.2f}   {lo}-{hi}  {'ok' if ok else 'FAIL'}")
    print("\nAverage by position group:")
    for g, rs in sorted(by_group.items()):
        print(f"  {g:<4}{statistics.fmean(rs):.2f}  (n={len(rs)})")
    print("\nAverage points per category (after damping):")
    for (g, cat), vs in sorted(by_cat.items()):
        print(f"  {g:<4}{cat:<16}{statistics.fmean(vs):+.2f}")
    print(f"\n{'All checks passed' if not failed else f'{failed} check(s) failed'}")
    return 1 if failed else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=120)
    ap.add_argument("--start", type=int, default=300000)
    a = ap.parse_args()
    sys.exit(run(a.n, a.start))
