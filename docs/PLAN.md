# Plan

Agreed 20 Oct 2026; video path updated 21 Oct; agents and model access updated 21 Oct. Submission deadline: 27 Oct 2026, 11:59 pm Pacific Time.

## Status (21 Oct)

For a full pick-up guide (branches, how to run, rules, what's waiting, ordered next steps) see [HANDOFF.md](HANDOFF.md).

- **Done, all in `main`:** event format v1, synthetic generator v1 with realism check, terminal match viewer, Interpret stage (ILikePotatoesALot/pitch-insights#1), Moment Scorer, replay server and the first version of the app (ILikePotatoesALot/pitch-insights#2), and the review fixes for the original code (ILikePotatoesALot/pitch-insights#3).
- **Azure:** moved from the school's student subscription (no chat-model quota) to Austin's personal Pay-As-You-Go subscription. Foundry in East US 2 with `gpt-4o` and `text-embedding-3-small`, both tested; quota for GPT-6 Luna was refused, so the agents stay on GPT-4o. Details: [DESIGN.md, Agents](DESIGN.md#agents).
- **Agents core merged** (ILikePotatoesALot/pitch-insights#4): Explainer and Narrator on GPT-4o through Agent Framework, code groundedness check with one retry and a fallback, stored commentary for the three samples (52 moments, all grounded), commentary shown in the app with an AI-generated note. Reviewed by `/code-review` and a second reviewer; all findings fixed.
- **Next, not blocked:** Memory agent (embeddings are deployed); SoccerTrack loader (data downloaded); Overlay Director; live simulation mode.
- **Waiting on Austin:** free-tier Content Safety, Translator and Speech resources and Application Insights (placeholders are in `.env`).
- **Decided 21 Oct:** the video path uses pre-trained detection on a short clip (fine-tuning maybe later); licensed footage is fine, so no clarification question; registration confirmed.
- **Team:** Austin and Claude. Teammates are GitHub collaborators but not registered participants (prize verification, rule 8.2).

## Concept

A live "match brain": specialist agents turn football events into scored, evidence-backed moments, render them on a Three.js 3D pitch with broadcast-style overlays, and personalise them per viewer.

- Demo hero: **same match, different viewers**, side by side.
- Category prize to aim for: Multi-Agent, with Foundry as a backup.

## Ground rules

- New project, started 20 Oct. The old CV project is reference only; no code copied.
- Fictional clubs and players. No Premier League names, logos or other trademarks.
- Only footage we have rights to. Main source: **SoccerTrack v2** (CC BY 4.0; amateur university players who gave informed consent, collected with ethics approval, no names). Credit it in the README and the demo video. In the demo, label its players as "Team Left #7" and so on, never with our fictional names.
- The core pipeline still runs on synthetic data (rules 4.7); real footage is used only for the video path. Austin confirmed on 21 Oct that licensed footage is fine.
- License: AGPL-3.0 for now. If we use RF-DETR (Apache-2.0) and drop Ultralytics, relicense the repo as MIT or Apache-2.0, which suits the Enterprise category better.

## 1. Ingest (two sources, one event format)

- **Synthetic generator** (main feed): possession chains, player profiles, pass difficulty, xG for shots, scripted storylines, a fake season history for milestones, and seeds so matches replay exactly. A check script compares output with real match averages.
- **Video path** (core; keep-or-cut decision on day 4), built on SoccerTrack v2:
  - **Footage:** 4K panoramic video from a fixed camera covering the whole pitch. Match 117093's first half is downloaded (video 3.35 GB, tracking ground truth 2.71 GB, events).
  - **Ground truth:** per-frame player positions in metres, track IDs, teams, roles and shirt numbers (GSR), plus timestamped events in 12 classes (BAS). Used to train the detector, and to measure our accuracy against.
  - **Detector:** **RF-DETR (small)** fine-tuned on SoccerTrack's boxes, with **YOLO** as the fallback. If time allows, fine-tune both and compare them against the ground truth. Check current versions, licenses and GPU memory needs before training.
  - **Training (optional):** start with the released RF-DETR on a short clip, no training. Fine-tune only if T4 GPU quota arrives in Azure ML (workspace `ML-pitch-insights`), or on Austin's GPU machine. The run is tracked and the model registered in **Azure ML** through MLflow, which needs no compute quota.
  - **Panoramic view:** players and the ball are small, so train and detect at high resolution (1280–1920 px) or on tiles. The fixed camera and SoccerTrack's calibration maps make pitch coordinates, speed and distance reliable. The ball is not in SoccerTrack's tracking ground truth, so ball detection is a bonus, not a dependency.
  - **Then:** ByteTrack for IDs, team from shirt colour (SoccerTrack's team labels only for scoring), and a Video Ingest agent writing `frame` messages and, when the ball is tracked well enough, events. Clips are processed ahead of time and replayed at match speed. Supplies measured speed and distance.
  - **Design details** (format traps in SoccerTrack's files, coordinate conversion, frame message, event mapping): [DESIGN.md, Video path](DESIGN.md#video-path).
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
- **Agents** (Agent Framework, planned): Memory agent (similar earlier moments, Foundry embeddings), Explainer (casual and analyst voices), groundedness check in code (one retry, then the fallback headline), Content Safety, Translator, Narrator. Commentary for the sample matches is generated ahead and stored, so the judges' demo never depends on rate limits. Details: [DESIGN.md, Agents](DESIGN.md#agents).

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

- Microsoft Agent Framework: Memory, Explainer, Narrator, Personalizer, Overlay Director, Scenario Director (and Video Ingest if the video path stays).
- Microsoft Foundry (East US 2): `gpt-4o` for the agents (GPT-6 Luna quota was refused), `text-embedding-3-small` for the Memory agent, groundedness evaluations, and tracing through Application Insights. GitHub Models as a fallback behind one `.env` setting.
- Azure AI services (free tiers): Content Safety, Translator, Speech (optional).
- Azure ML: experiment tracking and model registry for the detector; training on a cloud GPU (needs GPU quota) or Austin's GPU machine.
- Azure Container Apps (backend, detection run ahead of time), Static Web Apps (frontend), Key Vault with a managed identity, Cosmos DB free tier (viewer profiles, stored commentary).
- Optional: Event Hubs.

## Timeline

Rearranged again 21 Oct: the app was built a day early, the student subscription has no chat-model quota, and neither the GPU details nor the SoccerTrack download are in yet. The agents come first; the video path is decided on 23 Oct.

| Day | Date | Austin | Claude |
|---|---|---|---|
| 1 | 20 Oct | Register, Azure account | Repo, event format, generator v1 (done) |
| 2 | 21 Oct | Azure setup: personal Pay-As-You-Go subscription, Foundry with GPT-4o and embeddings, Azure ML workspace; SoccerTrack download (done) | Interpret stage, Moment Scorer, replay server and app, two code reviews; agents core, reviewed and merged (done) |
| 3 | 22 Oct | Free-tier Content Safety, Translator, Speech; Application Insights; T4 GPU quota request (only for fine-tuning) | Memory agent; SoccerTrack loader and conversion |
| 4 | 23 Oct | Test the commentary | Content Safety, Translator, tracing; detection on a short clip, pitch positions, benchmark; Overlay Director |
| 5 | 24 Oct | Personas, test explanations | Personalizer (favourite club and player, language, focus metric); live simulation mode and Scenario Director; video path work only if kept |
| 6 | 25 Oct | Test the UI | Deploy to Azure (Container Apps, Static Web Apps, Key Vault, Cosmos DB) |
| 7 | 26 Oct | Demo script | Polish, README (architecture, Microsoft technologies, groundedness scores) |
| 8 | 27 Oct | Record video, submit | Final fixes, make the repo public |

## Cut first if behind

Speech audio, then Event Hubs, then the video path (if not already cut on 23 Oct), then live simulation mode and the Scenario Director (replay still covers the demo), then 3D polish. Never cut the five stages, the stored commentary or the demo video.
