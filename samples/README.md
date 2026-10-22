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

## Video path (`video/`)

Output of the video path on real, licensed footage: [SoccerTrack v2](https://atomscott.github.io/SoccerTrack-v2/) (Scott et al., CC BY 4.0), match 117093, first half, 38:00–39:40. Kept in their own folder because every `.jsonl` directly in `samples/` is read as a demo match. Players are labelled by team and track ID ("L-t12"); SoccerTrack's players have no names, only side and shirt number. See [docs/DESIGN.md, Video path](../docs/DESIGN.md#video-path).

| File | Contents |
|---|---|
| `117093-38min.frames.jsonl` | 500 `frame` messages (schema 1.1), 5 a second |
| `117093-38min.events.jsonl` | Events derived from the tracked ball and players (`source: "video"`) |
| `117093-38min.benchmark.json` | Scores against SoccerTrack's ground truth |
| `117093-38min.calibration.json` | The fitted image-to-pitch mapping |
| `117093-38min_ft.*` | The same four files with the fine-tuned detector for people (recommended) |
| `117093-boxes.eval.json` | Pre-trained against fine-tuned detector boxes on SoccerTrack's held-out test frames |
