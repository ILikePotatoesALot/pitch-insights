# Plan

Agreed 20 Oct 2026; video path updated 21 Oct. Submission deadline: 27 Oct 2026, 11:59 pm Pacific Time.

## Status (21 Oct)

- **Done:** event format v1, synthetic generator v1 with realism check, terminal match viewer, Interpret stage (stats, patterns, win probability, live ratings, signals) merged into `main` via ILikePotatoesALot/pitch-insights#1. Moment Scorer, replay server and the first version of the app (3D pitch, moments feed, ratings, casual and analyst modes) on branch `pitch-frontend`.
- **Next, not blocked:** live simulation mode; Overlay Director (timed overlay cues); more Personalise options (favourite club and player, language).
- **Waiting on Austin:** GPU model, VRAM and OS (for detector training); a deployed Foundry GPT model with its endpoint and key in `.env` (for the agents); OK to download SoccerTrack match 117093's first half (3.35 GB).
- **Team:** Austin and Claude. Friends are listed only if they contribute (prize verification, rule 8.2).

## Concept

A live "match brain": specialist agents turn football events into scored, evidence-backed moments, render them on a Three.js 3D pitch with broadcast-style overlays, and personalise them per viewer.

- Demo hero: **same match, different viewers**, side by side.
- Category prize to aim for: Multi-Agent, with Foundry as a backup.

## Ground rules

- New project, started 20 Oct. The old CV project is reference only; no code copied.
- Fictional clubs and players. No Premier League names, logos or other trademarks.
- Only footage we have rights to. Main source: **SoccerTrack v2** (CC BY 4.0; amateur university players who gave informed consent, collected with ethics approval, no names). Credit it in the README and the demo video. In the demo, label its players as "Team Left #7" and so on, never with our fictional names.
- The core pipeline still runs on synthetic data (rules 4.7); real footage is used only for the video path. Mention this in the clarification question to the organisers.
- License: AGPL-3.0 for now. If we use RF-DETR (Apache-2.0) and drop Ultralytics, relicense the repo as MIT or Apache-2.0, which suits the Enterprise category better.

## 1. Ingest (two sources, one event format)

- **Synthetic generator** (main feed): possession chains, player profiles, pass difficulty, xG for shots, scripted storylines, a fake season history for milestones, and seeds so matches replay exactly. A check script compares output with real match averages.
- **Video path** (core; keep-or-cut decision on day 4), built on SoccerTrack v2:
  - **Footage:** 4K panoramic video from a fixed camera covering the whole pitch. Start with one half of match 117093 (3.35 GB).
  - **Ground truth:** per-frame player positions in metres, track IDs, teams, roles and shirt numbers (GSR), plus timestamped events in 12 classes (BAS). Used to train the detector, and to measure our accuracy against.
  - **Detector:** **RF-DETR (small)** fine-tuned on SoccerTrack's boxes, with **YOLO** as the fallback. If time allows, fine-tune both and compare them against the ground truth. Check current versions, licenses and GPU memory needs before training.
  - **Training:** on Austin's GPU machine (no Azure ML GPU quota). The run is tracked and the model registered in **Azure ML** through MLflow, which needs no compute quota.
  - **Panoramic view:** players and the ball are small, so train and detect at high resolution (1280–1920 px) or on tiles. The fixed camera and SoccerTrack's calibration maps make pitch coordinates, speed and distance reliable. The ball is not in SoccerTrack's tracking ground truth, so ball detection is a bonus, not a dependency.
  - **Then:** ByteTrack for IDs, team from shirt colour (SoccerTrack's team labels only for scoring), and a Video Ingest agent writing `frame` messages and, when the ball is tracked well enough, events. Clips are processed ahead of time and replayed at match speed. Supplies measured speed and distance.
  - **Design details** (format traps in SoccerTrack's files, coordinate conversion, frame message, event mapping): [DESIGN.md, Video path](DESIGN.md#video-path-planned).
  - **Benchmark:** position error and share of SoccerTrack's labelled events we detect, shown in the README and demo.
  - **Synthetic data:** use SoccerTrack's real tracking to calibrate movement (speeds, distances, team shape) for the v2 synthetic tracking frames.
- Stream over WebSocket or Server-Sent Events; Azure Event Hubs optional.
- Two ways to run a match: **replay** (default: generated up front, released on the match clock, with seek) and **live simulation** (generated step by step, with mid-match interventions from a Scenario Director agent; interventions are logged so the match can be replayed exactly).

## 2. Interpret (code first) — built

- Team and player stats, including PPDA, progressive actions and threat added (xT, learned from our own matches).
- Patterns over the last 5 minutes: momentum (with a per-minute series for the chart), pressure, chaos, tempo, field tilt.
- Live win probability.
- Live player ratings: start at 6.0, event-weighted, weighted by position, damped for playing time, with a breakdown that adds up to the rating. Calibrated against public rating systems.
- About 20 signals a match (goals, momentum swings, pressing spells, rating jumps, milestones) for the Moment Scorer.
- Physical stats (speed, distance) come with the `frame` messages in v2.
- The LLM only names and describes patterns. Details: [DESIGN.md, Interpret stage](DESIGN.md#interpret-stage-v1).

## 3. Explain

- **Moment Scorer** (code, built): ranks the Interpreter's signals into moments (about 4 headlines and 10 shown a match), each with an evidence pack and a fallback headline. Details: [DESIGN.md, Moment Scorer](DESIGN.md#explain-stage-moment-scorer-v1).
- Key moments get an evidence pack; the LLM explains only what is in it.
- A "Why?" button shows the evidence behind any moment or rating.

## 4. Render (Vite + React + Three.js)

- Backend outputs timed overlay cues as JSON (time, duration, priority, template, data).
- Three.js pitch surface shaped by live momentum, with spikes for shots. Own design.
- React overlays: lower-thirds, stat cards, player tags, speed popups, rating alerts.
- An Overlay Director agent prevents clutter.

## 5. Personalise (same renderer; the viewer profile decides)

- Profile: analyst or casual, club, favourite player, language, focus metric.
- Filters cues, rewrites tone and language, player-focus mode with a spotlight, favourite-player card with live rating and sparkline.
- Broadcast mode: overlays only. Fan mode: adds a side panel.

## Microsoft stack

- Foundry: GPT models and agents.
- Agent Framework agents: Ingest, Video Ingest, Stats/Pattern, Moment Scorer, Explainer, Narrator, Personalizer, Overlay Director.
- Azure ML: experiment tracking and model registry for the detector (training runs on Austin's GPU; no GPU quota needed).
- Azure Container Apps (backend, CPU detection service), Static Web Apps (frontend).
- Optional: Event Hubs, AI Speech.

## Timeline

Rearranged 21 Oct: the Interpret stage finished early and training waits for Austin's GPU, so the frontend and agents move earlier.

| Day | Date | Austin | Claude |
|---|---|---|---|
| 1 | 20 Oct | Register, Azure account | Repo, event format, generator v1 (done) |
| 2 | 21 Oct | Check GPU details; confirm a Foundry model is deployed | Interpret stage (done); SoccerTrack download and conversion to our event format and training data; training kit; Moment Scorer |
| 3 | 22 Oct | Run detector training on the GPU machine | Vite + React + Three.js pitch; replay server streaming to the browser |
| 4 | 23 Oct | Decide on the video path | Explainer and Narrator agents on Foundry; live simulation mode; video-to-events with the trained detector |
| 5 | 24 Oct | Personas, test explanations | Overlays, Personalizer, multi-language; Scenario Director |
| 6 | 25 Oct | Test the UI | Accuracy benchmark against SoccerTrack; deploy to Azure |
| 7 | 26 Oct | Demo script | Polish, README |
| 8 | 27 Oct | Record video, submit | Final fixes, make the repo public |

## Cut first if behind

Speech audio, then Event Hubs, then live simulation mode (replay still covers the demo), then 3D polish. Never cut the five stages or the demo video.
