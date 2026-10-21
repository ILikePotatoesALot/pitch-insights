# Pitch Insights

*Live football intelligence, explained and personalised.*

Pitch Insights is an AI system that turns live football match events into explainable insights for broadcasters and fans. It reads match data from a synthetic event generator and from computer-vision tracking of match video. Specialist AI agents built on Microsoft Foundry and Microsoft Agent Framework calculate stats and live player ratings, find the key moments, explain why they matter, and present them as on-screen overlays on a live 3D pitch. Each viewer can personalise the experience by club, favourite player, language and level of detail. It runs on Azure.

Built for the Microsoft Premier League Hackathon (October 2026).

Picking the project up? Start with [docs/HANDOFF.md](docs/HANDOFF.md).

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
python -m pitch_insights.watch ../samples/comeback-POT-CAR.jsonl --speed 60 --from 80   # watch it play out
python -m pitch_insights.interpret ../samples/comeback-POT-CAR.jsonl --at 70 --player Madekuta   # stats, ratings, signals
python scripts/seed_search.py --story comeback --home POT --away CAR
python scripts/validate_realism.py      # 300 matches against real-football ranges
pytest
```

### Run the app

Two terminals:

```
cd backend
.venv\Scripts\python -m uvicorn pitch_insights.server:app --port 8000
```

```
cd frontend
npm install
npm run dev
```

Then open http://localhost:5173. Pick a demo match, switch between casual fan and analyst, change speed, or jump to a minute.

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

## Live player ratings

Every player starts at 6.0 and moves with each action, weighted by position and damped by playing time, and every change is logged so the app can show why a rating is what it is. Over 120 generated matches (`scripts/calibrate_ratings.py`): average 6.8, spread 0.76, best player in a match about 8.5, and 9.5+ in about 10% of matches, in line with public rating systems. Every position averages 6.8–6.9. Details in [docs/DESIGN.md](docs/DESIGN.md#interpret-stage-v1).

## Agents and grounded commentary

The Explainer and Narrator agents, built with Microsoft Agent Framework on a Microsoft Foundry GPT-4o deployment, turn each key moment's evidence pack into commentary in two voices: casual and analyst. A code check confirms that every name and number they write is in the evidence. A draft that fails gets one retry with the problems named, and after that the moment keeps its plain headline. Commentary for the demo matches is generated ahead and stored, so the demo never waits on a model:

```
cd backend
.venv\Scripts\python scripts/generate_commentary.py
```

First full run: 52 moments across the three demo matches, all grounded, none fell back. Commentary is labelled as AI-generated in the app, and "Why?" shows the facts it came from. Details and the engineering practices we follow: [docs/DESIGN.md](docs/DESIGN.md#agents).

## Credits

- Player detection: [Roboflow football-players-detection](https://universe.roboflow.com/roboflow-jvuqo/football-players-detection-3zvbc) (CC BY 4.0)
- Video and ground truth for the video path: [SoccerTrack v2](https://atomscott.github.io/SoccerTrack-v2/) by Scott et al. (CC BY 4.0), [arXiv:2508.01802](https://arxiv.org/abs/2508.01802)
- All clubs, players and matches in the synthetic data are fictional.

## License

[GNU AGPL-3.0](LICENSE)
