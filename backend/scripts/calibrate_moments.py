"""Check how many moments of each tier the Moment Scorer picks per match.

Targets: 3-8 headlines and 8-15 headline-or-notable moments a typical match, so the
overlay has a handful of big moments and a steady supply of smaller ones.

    python scripts/calibrate_moments.py          # 120 matches
"""

import argparse
import itertools
import statistics
import sys
from collections import Counter

from pitch_insights.explain.moments import MatchBrain
from pitch_insights.generator.engine import simulate
from pitch_insights.generator.players import load_clubs

TARGETS = [("Headlines per match", "headline", 3, 8), ("Headline + notable per match", "shown", 8, 15)]

ap = argparse.ArgumentParser()
ap.add_argument("-n", type=int, default=120)
ap.add_argument("--start", type=int, default=800000)
args = ap.parse_args()

pairs = list(itertools.permutations(sorted(load_clubs()), 2))
per_match, by_type = [], Counter()
for i in range(args.n):
    meta, events, _ = simulate(args.start + i, *pairs[i % len(pairs)])
    brain = MatchBrain(meta)
    for e in events:
        brain.update(e)
    tiers = Counter(m["tier"] for m in brain.moments)
    per_match.append({"headline": tiers["headline"], "shown": tiers["headline"] + tiers["notable"],
                      "all": len(brain.moments)})
    for m in brain.moments:
        by_type[(m["type"], m["tier"])] += 1

failed = 0
for label, key, lo, hi in TARGETS:
    avg = statistics.fmean(r[key] for r in per_match)
    ok = lo <= avg <= hi
    failed += not ok
    print(f"{label:<32}{avg:>6.1f}   {lo}-{hi}  {'ok' if ok else 'FAIL'}")
print(f"{'All moments per match':<32}{statistics.fmean(r['all'] for r in per_match):>6.1f}")
print("\nMoments per match by type and tier:")
for (t, tr), n in sorted(by_type.items()):
    print(f"  {t:<18}{tr:<9}{n / args.n:>5.2f}")
print(f"\n{'All checks passed' if not failed else f'{failed} check(s) failed'}")
sys.exit(1 if failed else 0)
