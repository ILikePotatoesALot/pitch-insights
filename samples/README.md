# Demo matches

Three generated matches chosen with `scripts/seed_search.py`. Each `.jsonl` file has `match_meta` on the first line, then one event per line. The `.debug.json` files hold hidden generator values (match form, script) and are not for the agents. The `.commentary.json` files hold the stored commentary, and the `.memory.json` files the Memory agent's precomputed embeddings (`backend/scripts/embed_moments.py`).

| File | Seed | Result | Story |
|---|---|---|---|
| `comeback-POT-CAR.jsonl` | 52 | Potato FC 2–3 Carrot FC | Potato lead 2–1 until Carrot score at 88' and win it in the 96th minute |
| `thriller-CAR-BRO.jsonl` | 4 | Carrot FC 3–4 Broccoli FC | Seven goals; underdogs Broccoli win away |
| `red-card-CAU-POT.jsonl` | 24 | Cauliflower FC 2–0 Potato FC | Favourites Potato go down to ten at 20' and Cauliflower win |

Regenerate any of them with, for example:

```
python -m pitch_insights.generate --seed 52 --home POT --away CAR --out ../samples --name comeback-POT-CAR
```
