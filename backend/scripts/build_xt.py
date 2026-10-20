"""Learn the expected-threat grid from generated matches and save it.

    python scripts/build_xt.py            # 400 matches
"""

import argparse
import itertools
import json

from pitch_insights.generator.engine import simulate
from pitch_insights.generator.players import load_clubs
from pitch_insights.interpret.xt import COLS, GRID_FILE, ROWS, learn_grid

ap = argparse.ArgumentParser()
ap.add_argument("-n", type=int, default=400)
ap.add_argument("--start", type=int, default=200000)
args = ap.parse_args()

pairs = list(itertools.permutations(sorted(load_clubs()), 2))
matches = [simulate(args.start + i, *pairs[i % len(pairs)])[1] for i in range(args.n)]
grid = learn_grid(matches)
GRID_FILE.write_text(json.dumps({
    "description": "Expected threat per zone, learned from generated matches (scripts/build_xt.py)",
    "cols": COLS, "rows": ROWS, "matches": args.n, "seed_start": args.start,
    "grid": grid,
}, indent=1), encoding="utf-8")
print(f"Wrote {GRID_FILE}")
for r in reversed(range(ROWS)):
    print(" ".join(f"{grid[c][r]:.3f}" for c in range(COLS)))
