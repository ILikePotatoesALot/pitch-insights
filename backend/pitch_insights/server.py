"""Replay server: streams a match to the browser on the match clock.

    uvicorn pitch_insights.server:app --port 8000

GET  /api/matches                list of demo matches in samples/, then the video clip(s) in samples/video/
                                 (`kind` is "synthetic" or "video")
GET  /api/matches/{name}         that match's match_meta (a clip's is made up of its teams, Left and Right)
GET  /api/clubs                  the clubs and their squads (for the app's profile picker)
GET/PUT/DELETE /api/profile/{id} a viewer's saved choices (Cosmos DB when deployed; see pitch_insights/profiles.py)
WS   /ws/replay/{name}?speed=20&from=0&lang=en&at=0&mode=casual&team=POT&player=POT-09&focus=xg

The WebSocket sends, in order:
  {"type": "meta", "meta": ..., "commentary": {...}, "languages": {...}, "lang": "de", "profile": {...}}
                                                        commentary: who wrote the stored commentary
                                                        (model, prompt version, groundedness summary);
                                                        languages: those with stored translations;
                                                        profile: the viewer's choices as the server applied them
  {"type": "catchup", "moments": [...], "state": ..., "recent_events": [...], "position_events": [...]}
                                                        only when starting after kick-off; recent_events
                                                        (the last 3 minutes) let the pitch redraw at once;
                                                        position_events restore players' last known positions
  then, as the match clock reaches them:
  {"type": "event", "event": ...}
  {"type": "moment", "moment": ...}                     with "commentary" when the agents wrote some
  {"type": "state", "state": ...}                       about once a second
  {"type": "cue", "cue": ...}                           an overlay to show (the Overlay Director, see
                                                        pitch_insights/director); text in the viewer's language
  {"type": "cue_end", "id": "C-3", "reason": ...}       one to take down early ("preempted", or "withdrawn" when
                                                        the viewer's mode changed); cues otherwise
                                                        end when their `duration` (screen seconds) is up, which
                                                        the server watches, so a pause freezes them too
  {"type": "end"}                                       the final whistle; the connection stays open until the
                                                        cues still queued or on screen have run their course
The browser can send {"cmd": "speed", "value": 5}, {"cmd": "pause"}, {"cmd": "resume"} or
{"cmd": "detail", "value": "casual"} (the viewer's mode, "casual" or "analyst", the default: casual fans
get only the cues made for everyone, so cues they would never see can't hold a slot on their screen).
The viewer's profile comes with the connection (`mode`, `team`, `player`, `focus`; see
pitch_insights/director/personalise.py): the Director boosts cues about the favourite, adds alerts for the
favourite player and keeps cues about the other side from holding slots. A value that is missing, malformed or
not in this match is ignored. To seek, it reconnects with a different `from` minute, or `at` (match seconds, which wins when both are
given): a minute on the broadcast clock can say 47:00 of the second half but not 45+2 of the first.
"""

from __future__ import annotations

import asyncio
import contextlib
import functools
import json
import logging
import math
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from pitch_insights.agents.memory import memory_for
from pitch_insights.agents.store import commentary_info, load_commentary, with_commentary
from pitch_insights.agents.translate import LANGUAGES, TRANSLATION_VERSION, load_translations, translated_moment
from pitch_insights.director import CueBuilder, Personaliser, parse_profile, visible_to
from pitch_insights.director.session import CUE_TICK_S, ViewerSession, clamp_speed, run_until_first_done
from pitch_insights.explain.moments import MatchBrain
from pitch_insights.generator.io import read_match
from pitch_insights.generator.stream import Replay, match_seconds, start_seconds
from pitch_insights.origins import LOCALHOST, configured_origins, origin_allowed
from pitch_insights.profiles import close_store, router as profiles_router, warm_store
from pitch_insights.telemetry import setup_telemetry
from pitch_insights.video.replay import ClipError, clip_meta, find_clip, list_clips
from pitch_insights.video.serve import replay_clip

log = logging.getLogger("pitch_insights.server")
SAMPLES = Path(os.getenv("PITCH_SAMPLES", Path(__file__).resolve().parents[2] / "samples"))
STATE_EVERY_S = 1.0  # wall-clock seconds between state messages

@contextlib.asynccontextmanager
async def lifespan(_: FastAPI):
    warm = asyncio.create_task(warm_store())  # in the background: the server answers while it signs in to Cosmos DB
    yield
    warm.cancel()
    await close_store()


app = FastAPI(title="Pitch Insights replay server", lifespan=lifespan)
# Only the static site (PITCH_ALLOWED_ORIGINS) and localhost may call this from a page; see pitch_insights/origins.py.
app.add_middleware(CORSMiddleware, allow_origins=configured_origins(), allow_origin_regex=LOCALHOST,
                   allow_methods=["GET", "PUT", "DELETE"], allow_headers=["Content-Type"])
app.include_router(profiles_router)
setup_telemetry(app)


def _match_path(name: str) -> Path:
    path = (SAMPLES / f"{name}.jsonl").resolve()
    if path.parent != SAMPLES.resolve() or not path.exists():
        raise HTTPException(404, f"no match called {name!r}")
    return path


@app.get("/api/matches")
def list_matches() -> list[dict]:
    out = []
    for path in sorted(SAMPLES.glob("*.jsonl")):
        with path.open(encoding="utf-8") as f:
            meta = json.loads(f.readline())
        out.append({"name": path.stem, "match_id": meta["match"]["id"],
                    "kind": "synthetic",
                    "home": {k: meta["home"][k] for k in ("id", "name", "short_name", "colours")},
                    "away": {k: meta["away"][k] for k in ("id", "name", "short_name", "colours")}})
    return out + list_clips(SAMPLES)  # the real-footage clip(s) in samples/video/, listed after the synthetic matches


@functools.lru_cache(maxsize=4)
def _clubs(files: tuple[tuple[str, int], ...]) -> list[dict]:
    """The clubs in these sample files (path and modification time, so a changed file is read again)."""
    clubs: dict[str, dict] = {}
    for path in (Path(p) for p, _ in files):
        with path.open(encoding="utf-8") as f:
            meta = json.loads(f.readline())
        for side in ("home", "away"):
            t = meta[side]
            clubs.setdefault(t["id"], {k: t[k] for k in ("id", "name", "short_name", "colours")} | {
                "players": [{k: p[k] for k in ("id", "name", "number", "position")} for p in t["players"]]})
    return sorted(clubs.values(), key=lambda c: c["name"])


@app.get("/api/clubs")
def list_clubs() -> list[dict]:
    """Each club in the samples with its squad: what the profile picker offers as a favourite club and player."""
    return _clubs(tuple((str(p), p.stat().st_mtime_ns) for p in sorted(SAMPLES.glob("*.jsonl"))))


@app.get("/api/matches/{name}")
def get_match(name: str) -> dict:
    clip = find_clip(SAMPLES, name)
    if clip:
        return clip_meta(clip)
    meta, _ = read_match(_match_path(name))
    return meta


def state_message(brain: MatchBrain) -> dict:
    """The live state the app needs, kept small enough to send every second."""
    snap = brain.interp.snapshot(top_moments=3)
    players = []
    for pid, p in snap["players"].items():
        players.append({k: p[k] for k in ("player_id", "team_id", "name", "number", "position", "minutes",
                                           "on_pitch", "rating", "goals", "assists", "shots", "xg", "passes",
                                           "passes_complete", "key_passes", "tackles_won", "interceptions",
                                           "dribbles_won", "saves", "xt_added", "by_category", "key_moments")})
    return {k: snap[k] for k in ("clock", "period", "match_minute", "finished", "score", "win_probability",
                                  "teams", "patterns", "momentum_series")} | {"players": players}


def position_events(events: list[dict]) -> list[dict]:
    """A bounded set of past events that restores every player's last known position, in time order."""
    last: dict[str, int] = {}
    for i, ev in enumerate(events):
        if not ev.get("team_id"):
            continue
        if ev.get("player_id") and ev.get("x") is not None and ev.get("y") is not None:
            last[ev["player_id"]] = i
        if (ev["type"] == "pass" and ev.get("outcome") == "complete" and ev.get("receiver_id")
                and ev.get("end_x") is not None and ev.get("end_y") is not None):
            last[ev["receiver_id"]] = i
    return [events[i] for i in sorted(set(last.values()))]


@app.websocket("/ws/replay/{name}")
async def replay(ws: WebSocket, name: str, speed: float = 20.0):
    if not origin_allowed(ws.headers.get("origin")):  # CORS doesn't cover WebSockets, so check the page's origin here
        log.warning("refused a replay from origin %r: add it to PITCH_ALLOWED_ORIGINS if it should be allowed", ws.headers.get("origin"))
        await ws.close(code=1008)
        return
    await ws.accept()
    try:
        clip = find_clip(SAMPLES, name)  # a tracked video clip (samples/video/), not a synthetic match
    except ClipError as e:  # a clip whose files are missing something or damaged
        await ws.send_json({"type": "error", "message": str(e)})
        await ws.close()
        return
    if clip:
        await replay_clip(ws, clip, speed, SAMPLES)
        return
    try:
        path = _match_path(name)
        meta, events = read_match(path)
    except HTTPException as e:
        await ws.send_json({"type": "error", "message": e.detail})
        await ws.close()
        return
    try:  # "from" is a Python keyword, so read it directly
        from_minute = max(0.0, float(ws.query_params.get("from", 0)))
    except ValueError:
        from_minute = 0.0
    brain = MatchBrain(meta, memory=memory_for(path, meta))  # stored vectors: no network
    stored = load_commentary(path)
    saved = load_translations(path)  # stored too: no network; a file made by an older method isn't used
    translations = saved["moments"] if saved.get("version") == TRANSLATION_VERSION else {}
    languages = {"en": "English"} | (LANGUAGES if translations else {})
    lang = ws.query_params.get("lang", "en")
    lang = lang if lang in languages else "en"

    def shown(m: dict) -> dict:
        """A moment as this viewer sees it: with its stored commentary, in their language."""
        m = with_commentary(m, stored, meta)
        return translated_moment(m, translations.get(m["id"]), lang)

    profile = parse_profile(ws.query_params, meta)  # checked against this match: a bad value is ignored
    await ws.send_json({"type": "meta", "meta": meta, "commentary": commentary_info(stored),
                        "languages": languages, "lang": lang, "profile": profile.public()})

    try:  # exact match seconds: a reconnect that must land on the same second, which a minute can't
        at = float(ws.query_params["at"]) if "at" in ws.query_params else None  # (no `from` for 45+2')
    except ValueError:
        at = None
    if at is not None and math.isfinite(at):
        start = max(0.0, at)
    else:
        start = start_seconds(events, from_minute) if from_minute > 0 else 0.0
    times = match_seconds(events)
    first = next((i for i, t in enumerate(times) if t >= start), len(events))
    for ev in events[:first]:
        brain.update(ev)
    if first:
        recent = [ev for ev, t in zip(events[:first], times[:first])
                  if t >= times[first - 1] - 180 or (ev["type"] == "match_state" and ev["state"] == "half_time")]
        await ws.send_json({"type": "catchup", "moments": [shown(m) for m in brain.moments],
                            "state": state_message(brain), "recent_events": recent,
                            "position_events": position_events(events[:first])})
    else:  # from kick-off there is no catch-up, but the app still needs the starting XI at their opening ratings
        await ws.send_json({"type": "state", "state": state_message(brain)})

    rep = Replay(events, speed=clamp_speed(speed), start_at=times[first] if first < len(events) else start, poll=0.05)
    # The Overlay Director, one per connection (see director/session.py). A seek or a language change reconnects,
    # so cues start afresh.
    session = ViewerSession(ws, rep, profile.mode)
    builder = CueBuilder(meta)
    personaliser = Personaliser(profile, meta)  # the favourites and focus metric: boosts, alerts, relevance

    async def play():
        loop = asyncio.get_running_loop()
        last_state = 0.0
        while True:
            try:  # wake up between events too, so cues end and start on time even in a quiet spell
                ev = await asyncio.wait_for(rep.__anext__(), CUE_TICK_S)
            except asyncio.TimeoutError:
                await session.tick()
                continue
            except StopAsyncIteration:
                break
            out = brain.update(ev)
            await ws.send_json({"type": "event", "event": ev})
            shown_moments = [shown(m) for m in out["moments"]]
            for m in shown_moments:
                await ws.send_json({"type": "moment", "moment": m})
            state = None
            if loop.time() - last_state >= STATE_EVERY_S or ev["type"] in ("shot", "match_state") or out["moments"]:
                state = state_message(brain)
                await ws.send_json({"type": "state", "state": state})
                last_state = loop.time()
            cues = [c for c in personaliser.cues(builder, ev, shown_moments, state, lambda: state_message(brain), rep.now)
                    if visible_to(c, session.viewer["detail"])]
            if cues:
                await session.tick()  # mode changes and expiries first, so the new cues meet the screen as it is
                await session.send_all(session.director.offer(cues, session.show_now()))
            else:
                await session.tick()
        await ws.send_json({"type": "state", "state": state_message(brain)})
        await ws.send_json({"type": "end"})
        await session.finish()

    await run_until_first_done(play(), session.listen())
