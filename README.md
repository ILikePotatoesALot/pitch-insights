# Pitch Insights

*Live football intelligence, explained and personalised.*

Pitch Insights is an AI system that turns live football match events into explainable insights for broadcasters and fans. It reads match data from a synthetic event generator and from computer-vision tracking of match video. Specialist AI agents built on Microsoft Foundry and Microsoft Agent Framework calculate stats and live player ratings, find the key moments, explain why they matter, and present them as on-screen overlays on a live 3D pitch. Each viewer can personalise the experience by club, favourite player, language and level of detail. It runs on Azure.

Built for the Microsoft Premier League Hackathon (October 2026).

Picking the project up? Start with [docs/HANDOFF.md](docs/HANDOFF.md).

## Pipeline

1. **Ingest**: synthetic match events, plus player positions and events derived from real, licensed match video (RF-DETR detection on tiles, ByteTrack-style tracking, a fitted image-to-pitch mapping), in one shared event format.
2. **Interpret**: stats, patterns (momentum, pressure, chaos, tempo) and live player ratings, calculated in code.
3. **Explain**: each moment is scored by how much it changed the match, and explained from an evidence pack of computed facts.
4. **Render**: timed, machine-readable overlay cues, drawn on a Three.js 3D pitch.
5. **Personalise**: analyst or casual mode, favourite club and player, language and focus metric.

## Repository layout

| Folder | Contents |
|---|---|
| `backend/` | Python: event generator, video loader and scoring (pure Python), stats, agents, event stream |
| `video/` | The video path's detector and scripts, in their own environment (`video\.venv`: torch CPU, rfdetr, opencv) |
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

Every line is then screened by **Azure AI Content Safety** (blocked at the lowest harm level, and not shown if the service can't be reached), and **Foundry's groundedness evaluator** gives a second opinion: all 52 stored lines pass, the lowest scoring 4 out of 5. **Azure AI Translator** puts every moment into Spanish, French, German, Dutch and Simplified Chinese, with player and club names and match clocks protected, and a translation that loses a name or number keeps its English (9 of 3,180 did). Agent runs are traced to **Application Insights** through Agent Framework's OpenTelemetry instrumentation, without prompts or replies.

```
cd backend
.venv\Scripts\python scripts/translate_moments.py
.venv\Scripts\python scripts/evaluate_groundedness.py
```

First full run: 52 moments across the three demo matches, all grounded, none fell back. Commentary is labelled as AI-generated in the app, and "Why?" shows the facts it came from. Details and the engineering practices we follow: [docs/DESIGN.md](docs/DESIGN.md#agents).

## Video path: real footage into the same messages

The core pipeline runs on synthetic matches. As a second source, the video path turns real, licensed match video into the same `frame` and `event` messages: [SoccerTrack v2](https://atomscott.github.io/SoccerTrack-v2/) (Scott et al., CC BY 4.0), a fixed 4K panoramic camera over a whole pitch, amateur university players who consented, no names. Players are labelled by side and shirt number ("Left #7"), never with our fictional names.

**RF-DETR** (small, pre-trained, no fine-tuning, on CPU) runs on 5 × 2 tiles of each frame. A 2-D polynomial, fitted on frames before the clip, maps feet in the image to pitch metres (one homography can't describe a stitched panorama). A ByteTrack-style tracker works in pitch metres, shirt colours give the teams, and possession of the tracked ball gives passes, carries and turnovers with a `confidence`.

Benchmarked against SoccerTrack's ground truth on 100 s of match 117093 (38:00–39:40, the build-up to a goal, 500 frames at 5 fps):

| | |
|---|---|
| Players found | 91% |
| Position error | 0.78 m mean, 0.59 m median |
| Precision | 85% (the rest are officials, who aren't in the ground truth, people behind the goals and spectators the filter missed) |
| Team from shirt colour | 88% |
| Events matching SoccerTrack's within ±5 s | 74% of ours; 38% of theirs found |
| Detection time | 7.7 s a frame on CPU (64 min for the clip) |

The team, ID and event settings were chosen on this clip, so those figures are optimistic until checked on another; details, limits and how to run it in [docs/DESIGN.md, Video path](docs/DESIGN.md#video-path). The output is in [`samples/video/`](samples/README.md#video-path-video).

## Credits

- Player and ball detection: [RF-DETR](https://github.com/roboflow/rf-detr) by Roboflow (Apache-2.0), small model with its pre-trained COCO weights as released
- Video and ground truth for the video path: [SoccerTrack v2](https://atomscott.github.io/SoccerTrack-v2/) by Scott et al. (CC BY 4.0), [arXiv:2508.01802](https://arxiv.org/abs/2508.01802)
- Tracking follows the idea of [ByteTrack](https://arxiv.org/abs/2110.06864) (Zhang et al.); the code is our own
- All clubs, players and matches in the synthetic data are fictional.

## License

[Apache-2.0](LICENSE); see [NOTICE](NOTICE) for third-party work. The repo was AGPL-3.0 while YOLO (Ultralytics) was planned as the detector; it was relicensed on 22 Oct 2026 once RF-DETR (Apache-2.0) replaced it.
