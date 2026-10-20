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

Copy `.env.example` to `.env` and fill in your Azure details. Setup steps for the backend and frontend will be added as they are built.

## Credits

- Player detection: [Roboflow football-players-detection](https://universe.roboflow.com/roboflow-jvuqo/football-players-detection-3zvbc) (CC BY 4.0)
- All clubs, players and matches in the synthetic data are fictional.

## License

[GNU AGPL-3.0](LICENSE)
