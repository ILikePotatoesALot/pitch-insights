"""How busy the screen is: the Director's cue sheet for each sample match at several replay speeds.

    python scripts/calibrate_director.py

Prints, per match and speed, how many cues were offered, shown, pre-empted and dropped (and why), the most
cues on screen at once, the longest gap with an empty screen, and how long the lower-thirds were up. Checks
the clutter rules on every sheet and exits with an error if one is broken.
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from pitch_insights.director import CARD_TEMPLATES, DEFAULT_RULES  # noqa: E402
from pitch_insights.director.sheet import cue_sheet  # noqa: E402
from pitch_insights.generator.io import read_match  # noqa: E402

PACES = (1, 20, 60)


def check(sheet: list[dict], rules=DEFAULT_RULES) -> dict:
    """Replay the messages and make sure the screen never breaks the rules; returns the busiest moment."""
    live: dict[str, dict] = {}
    peak = 0
    for entry in sheet:
        msg = entry["message"]
        if msg["type"] == "cue":
            c = msg["cue"]
            live[c["id"]] = c
        else:
            live.pop(msg["id"])
        cues = list(live.values())
        by_template = Counter(c["template"] for c in cues)
        assert max(by_template.values(), default=0) <= 1, f"two cues of one template at {entry['show']}s"
        assert sum(c["template"] in CARD_TEMPLATES for c in cues) <= rules.max_cards, f"too many cards at {entry['show']}s"
        assert len(cues) <= rules.max_total, f"too many cues at {entry['show']}s"
        peak = max(peak, len(cues))
    return {"peak": peak}


def main():
    for path in sorted((ROOT / "samples").glob("*.jsonl")):
        meta, events = read_match(path)
        print(path.stem)
        for pace in PACES:
            sheet = cue_sheet(meta, events, pace)
            shown = [e["message"]["cue"] for e in sheet if e["message"]["type"] == "cue"]
            ended = Counter(e["message"]["reason"] for e in sheet if e["message"]["type"] == "cue_end")
            by_template = Counter(c["template"] for c in shown)
            stats = check(sheet)
            delayed = sum(1 for c in shown if c.get("delay", 0) > 0)
            print(f"  {pace:>3}x  shown {len(shown):>3} ({', '.join(f'{t} {n}' for t, n in sorted(by_template.items()))})"
                  f"  preempted {ended['preempted']}  delayed {delayed}  peak on screen {stats['peak']}")


if __name__ == "__main__":
    main()
