# Submission text (draft)

Draft text for the hackathon's submission form, to adapt to its fields and limits. Live app: https://blue-moss-06018420f.1.azurestaticapps.net · Repo: https://github.com/ILikePotatoesALot/pitch-insights · Demo video: *(add link)*

## Project name

Pitch Insights

## Tagline (one line)

Live football intelligence, explained and personalised: AI agents turn match events into checked, translated insight that every viewer sees their own way.

## Short description (about 50 words)

Pitch Insights turns football match events into explainable insight on a live 3D pitch. Code computes stats, ratings and win probability; agents on Microsoft Agent Framework and Foundry explain the key moments from that evidence, checked for grounding and safety and translated into five languages. Each viewer gets their own overlays, favourites and language.

## Full description

**What it does.** Pitch Insights replays synthetic football matches and a tracked real-footage clip on a live 3D pitch, with AI commentary for both. For synthetic matches, an Interpreter computes stats, momentum, win probability and live player ratings from every event. A Moment Scorer picks the moments that changed the match and packs the evidence behind each one. Agents built with Microsoft Agent Framework on Microsoft Foundry (GPT-4o) turn that evidence into commentary in two voices, casual and analyst, and a Memory agent recalls similar earlier moments with Foundry embeddings. An Overlay Director schedules broadcast-style overlays so the screen never clutters, and each viewer personalises the experience: favourite club and player (with a spotlight that follows them on the pitch and their own alerts), language, level of detail and one focus metric. Two viewers watching the same match see it differently, side by side.

The real-footage view brings 100 seconds of licensed match video (SoccerTrack v2) into the same app through an RF-DETR detector we fine-tuned. A dedicated Video Narrator agent describes five passages of detected play in casual and analyst voices, hedging events below 60% confidence and making no claims about goals or the score. Viewers can tap a marker or player row to follow that player's tracked position with a spotlight, alongside possession, distance and top-speed estimates from the tracking. Labels such as "Left #11" are tracker IDs, not shirt numbers or player identities. On this clip, tracked-player precision is 97%, recall is 93% and mean position error is 0.76 m against the dataset's ground truth. Tracker, team and event settings were chosen on this clip, so these figures need checking on another clip.

**The problem it solves.** Match data is abundant, but most viewers get the same generic graphics, and AI commentary can't be trusted if it invents facts. Pitch Insights explains only what the data shows, proves it ("Why?" shows the evidence), and fits the explanation to the viewer: a casual fan in their language, or an analyst who wants the numbers.

**How we kept the AI trustworthy.** Every line is checked in code against the evidence (one retry, then a plain headline), screened by Azure AI Content Safety (fails closed), and scored by Foundry's groundedness evaluator. All 52 synthetic-match moments and all five clip passages pass, with a lowest score of 4 out of 5 in each set. Clip checks also reject unsupported event types and require hedging for low-confidence detections. Azure AI Translator translates into Spanish, French, German, Dutch and Simplified Chinese, with names and clocks protected and every number checked. Commentary and translations are labelled as AI-generated, the real-footage view shows the model's measured accuracy, and profiles hold only five choices with no account or history.

**Microsoft and Azure technologies.**

- Microsoft Agent Framework: the Explainer, Narrator, Video Narrator and Memory agents
- Microsoft Foundry: GPT-4o and `text-embedding-3-small`, plus the groundedness evaluator
- Azure AI Content Safety and Azure AI Translator
- Application Insights with OpenTelemetry tracing
- Azure Machine Learning (MLflow) for the detector's benchmark runs
- Azure Container Apps and Container Registry (replay server, WebSocket streaming)
- Azure Static Web Apps (the app)
- Azure Cosmos DB, free tier (viewer profiles, managed identity, keys disabled)
- Azure Key Vault with managed identities
- GitHub Actions deploying with OpenID Connect

**How it's built.** Python (FastAPI) backend, React and Three.js frontend, a synthetic match generator checked against real-football ranges over 300 matches, and 425 automated tests (418 backend and seven frontend). The agents run ahead of time and their checked commentary is stored, so the live app never waits on a model.

**What's next.** Live simulation driven by a Scenario Director agent, positions from video for every match, and a per-viewer full-time recap.

## Notes for Austin

- Check the form's field names and word limits and trim to fit; the short description is the fallback for small boxes.
- Add the demo video link here and in the README's "Try it" section.
- The repo must be public before submitting.
