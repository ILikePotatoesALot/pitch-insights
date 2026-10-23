"""Replay server: streams a match to the browser on the match clock.

    uvicorn pitch_insights.server:app --port 8000

GET  /api/matches                list of demo matches in samples/
GET  /api/matches/{name}         that match's match_meta
GET  /api/clubs                  the clubs and their squads (for the app's profile picker)
WS   /ws/replay/{name}?speed=20&from=0&lang=en&at=0&mode=casual&team=POT&player=POT-09&focus=xg

The WebSocket sends, in order:
  {"type": "meta", "meta": ..., "commentary": {...}, "languages": {...}, "lang": "de", "profile": {...}}
                                                        commentary: who wrote the stored commentary
                                                        (model, prompt version, groundedness summary);
                                                        languages: those with stored translations;
                                                        profile: the viewer's choices as the server applied them
  {"type": "catchup", "moments": [...], "state": ..., "recent_events": [...]}
                                                        only when starting after kick-off; recent_events
                                                        (the last 3 minutes) let the pitch redraw at once
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
import json
import math
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from pitch_insights.agents.memory import memory_for
from pitch_insights.agents.store import load_commentary, with_commentary
from pitch_insights.agents.translate import LANGUAGES, TRANSLATION_VERSION, load_translations, translated_moment
from pitch_insights.director import CueBuilder, Director, Personaliser, ShowClock, parse_profile, visible_to
from pitch_insights.explain.moments import MatchBrain
from pitch_insights.generator.io import read_match
from pitch_insights.generator.stream import Replay, match_seconds, start_seconds

SAMPLES = Path(os.getenv("PITCH_SAMPLES", Path(__file__).resolve().parents[2] / "samples"))
STATE_EVERY_S = 1.0  # wall-clock seconds between state messages
CUE_TICK_S = 0.25  # how often the Director looks for cues that are over or can now start
MIN_SPEED, MAX_SPEED = 0.1, 600.0


def clamp_speed(speed: float) -> float:
    return max(MIN_SPEED, min(MAX_SPEED, speed))

app = FastAPI(title="Pitch Insights replay server")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"], allow_headers=["*"])


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
                    "home": {k: meta["home"][k] for k in ("id", "name", "short_name", "colours")},
                    "away": {k: meta["away"][k] for k in ("id", "name", "short_name", "colours")}})
    return out


@app.get("/api/clubs")
def list_clubs() -> list[dict]:
    """Each club in the samples with its squad: what the profile picker offers as a favourite club and player."""
    clubs: dict[str, dict] = {}
    for path in sorted(SAMPLES.glob("*.jsonl")):
        with path.open(encoding="utf-8") as f:
            meta = json.loads(f.readline())
        for side in ("home", "away"):
            t = meta[side]
            clubs.setdefault(t["id"], {k: t[k] for k in ("id", "name", "short_name", "colours")} | {
                "players": [{k: p[k] for k in ("id", "name", "number", "position")} for p in t["players"]]})
    return sorted(clubs.values(), key=lambda c: c["name"])


@app.get("/api/matches/{name}")
def get_match(name: str) -> dict:
    meta, _ = read_match(_match_path(name))
    return meta


def commentary_info(stored: dict) -> dict | None:
    """Who wrote the stored commentary, for the app's AI-generated label."""
    if not stored["moments"]:
        return None
    return {k: stored.get(k) for k in ("ai_generated", "provider", "model", "prompt_version", "summary")}


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


@app.websocket("/ws/replay/{name}")
async def replay(ws: WebSocket, name: str, speed: float = 20.0):
    await ws.accept()
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
                            "state": state_message(brain), "recent_events": recent})

    rep = Replay(events, speed=clamp_speed(speed), start_at=times[first] if first < len(events) else start, poll=0.05)
    # The Overlay Director: one per connection, working in screen seconds (a cue lasts as long on the
    # screen at 60x as at 1x). A seek or a language change reconnects, so cues start afresh.
    director, builder, clock = Director(), CueBuilder(meta), ShowClock()
    personaliser = Personaliser(profile, meta)  # the favourites and focus metric: boosts, alerts, relevance
    # Whose screen the Director is keeping clean: what the browser last asked for, and what the Director has
    # been reconciled to (listen() only asks; play() does the sending, so two tasks never write at once).
    viewer = {"detail": profile.mode, "applied": profile.mode}

    def show_now() -> float:
        return clock.at(rep.now, rep.speed)

    async def listen():
        """Apply the browser's commands. Ends (with WebSocketDisconnect) when the browser goes away."""
        while True:
            try:
                msg = await ws.receive_json()
            except ValueError:
                continue  # not JSON: ignore it rather than stop listening
            if not isinstance(msg, dict):
                continue
            cmd = msg.get("cmd")
            if cmd == "speed":
                try:
                    value = clamp_speed(float(msg["value"]))
                except (KeyError, TypeError, ValueError):
                    continue
                show_now()  # the time so far passed at the old speed
                rep.set_speed(value)
            elif cmd == "pause":
                show_now()
                rep.pause()
            elif cmd == "resume":
                rep.resume()
            elif cmd == "detail" and msg.get("value") in ("casual", "analyst"):
                viewer["detail"] = msg["value"]

    async def send_all(messages: list[dict]):
        for msg in messages:
            await ws.send_json(msg)

    async def tick():
        """The Director's turn between events: a changed viewer mode first (cues that viewer would never see
        come down at once, and don't sit in the queue holding slots), then the passing of time."""
        if viewer["applied"] != viewer["detail"]:
            viewer["applied"] = viewer["detail"]
            await send_all(director.withdraw(lambda c: not visible_to(c, viewer["applied"]), show_now()))
        await send_all(director.advance(show_now()))

    async def play():
        loop = asyncio.get_running_loop()
        last_state = 0.0
        while True:
            try:  # wake up between events too, so cues end and start on time even in a quiet spell
                ev = await asyncio.wait_for(rep.__anext__(), CUE_TICK_S)
            except asyncio.TimeoutError:
                await tick()
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
                    if visible_to(c, viewer["detail"])]
            if cues:
                await tick()  # mode changes and expiries first, so the new cues meet the screen as it is
                await send_all(director.offer(cues, show_now()))
            else:
                await tick()
        await ws.send_json({"type": "state", "state": state_message(brain)})
        await ws.send_json({"type": "end"})
        while director.waiting or director.on_screen:  # the last cues get their turn and are taken down
            await asyncio.sleep(CUE_TICK_S)
            await tick()
        await ws.close()

    # Run both together: whichever finishes first (the match ends, or the browser disconnects,
    # even while paused) stops the other, so nothing is left running for a closed tab.
    tasks = {asyncio.create_task(play()), asyncio.create_task(listen())}
    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    for task in pending:
        task.cancel()
    await asyncio.gather(*pending, return_exceptions=True)
    for task in done:
        exc = task.exception()
        if exc and not isinstance(exc, (WebSocketDisconnect, RuntimeError)):
            raise exc
