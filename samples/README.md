# Demo matches

Three generated matches chosen with `scripts/seed_search.py`. Each `.jsonl` file has `match_meta` on the first line, then one event per line. The `.debug.json` files hold hidden generator values (match form, script) and are not for the agents.

| File | Seed | Result | Story |
|---|---|---|---|
| `comeback-NBR-KSW.jsonl` | 176 | Northbridge FC 3–2 Kingswell Athletic | Northbridge lead early, fall 1–2 behind, then score twice to win with an 80' goal |
| `thriller-KSW-IRM.jsonl` | 4 | Kingswell Athletic 3–3 Ironmoor United | Ironmoor go 2–0 up away, Kingswell level before half-time, and it swings to 3–3 |
| `red-card-RVH-NBR.jsonl` | 30 | Ravensholt City 1–2 Northbridge FC | Ravensholt go down to ten at 32' with the score 0–0; Northbridge take control |

Regenerate any of them with, for example:

```
python -m pitch_insights.generate --seed 176 --home NBR --away KSW --out ../samples --name comeback-NBR-KSW
```
