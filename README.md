# Pitch Insights

*Live football intelligence, explained and personalised.*

Pitch Insights is an AI system that turns live football match events into explainable insights for broadcasters and fans. It reads match data from a synthetic event generator and from computer-vision tracking of match video. Specialist AI agents built on Microsoft Foundry and Microsoft Agent Framework calculate stats and live player ratings, find the key moments, explain why they matter, and present them as on-screen overlays on a live 3D pitch. Each viewer can personalise the experience by club, favourite player, language and level of detail. It runs on Azure.

Built for the Microsoft Premier League Hackathon (October 2026).

## Pipeline

1. **Ingest**: synthetic match events, plus events derived from match video (YOLO detection, ByteTrack, pitch homography), in one shared event format.
2. **Interpret**: stats, patterns (momentum, pressure, chaos, tempo) and live player ratings, calculated in code.
3. **Explain**: each moment is scored by how much it changed the match, and explained from an evidence pack of computed facts.
4. **Render**: timed, machine-readable overlay cues, drawn on a Three.js 3D pitch.
5. **Personalise**: analyst or casual mode, favourite club and player, language and focus metric.

## Repository layout

| Folder | Contents |
|---|---|
| `backend/` | Python: event generator, video ingest, stats, agents, event stream |
| `frontend/` | Vite + React + Three.js viewer and overlays |
| `docs/` | Plan and design notes |

## Setup

Copy `.env.example` to `.env` and fill in your Azure details.

### Backend (Python 3.12)

```
cd backend
py -3.12 -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
```

### Generate a match

```
python -m pitch_insights.generate --seed 42 --home POT --away CAR --out ../data
python scripts/seed_search.py --story comeback --home POT --away CAR
python scripts/validate_realism.py      # 300 matches against real-football ranges
pytest
```

Ready-made demo matches are in [`samples/`](samples/README.md). The event format is described in [docs/DESIGN.md](docs/DESIGN.md), with JSON Schemas in `docs/schema/`.

## Synthetic data realism

Averages over 300 generated matches (`scripts/validate_realism.py`; full output in [docs/realism-check.txt](docs/realism-check.txt)):

| Stat | Generated | Real-football target |
|---|---|---|
| Passes per team | 554 | 400–600 |
| Pass accuracy | 83.9% | 75–88% |
| Shots per team | 13.5 | 8–18 |
| xG per match | 2.8 | 2.5–3.5 |
| Goals per match | 2.9 | 2.5–3.0 |
| Yellow cards per match | 3.2 | 3–4 |
| Fouls per team | 9.4 | 9–13 |
| Corners per team | 5.0 | 4–7 |
| Penalties per match | 0.3 | 0.2–0.4 |
| Home win / draw / away win | 43 / 24 / 33% | about 45 / 25 / 30% |

Each club's style shows in its numbers: the high-press side makes the most pressures, the possession side has the best pass accuracy, and the direct side plays the longest passes.

## Credits

- Player detection: [Roboflow football-players-detection](https://universe.roboflow.com/roboflow-jvuqo/football-players-detection-3zvbc) (CC BY 4.0)
- All clubs, players and matches in the synthetic data are fictional.

## License

[GNU AGPL-3.0](LICENSE)
