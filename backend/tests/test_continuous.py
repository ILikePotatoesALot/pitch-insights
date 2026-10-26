import math

import pytest
from fastapi.testclient import TestClient

from pitch_insights.events.schema import event_adapter
from pitch_insights.explain.moments import MatchBrain
from pitch_insights.generator.continuous import ContinuousMatch, prototype
from pitch_insights.server import app


def absolute(player):
    return (player["x"], player["y"]) if player["team_id"] == "POT" else (105 - player["x"], 68 - player["y"])


def test_reproducible_positions_and_events():
    assert ContinuousMatch(42).run(30) == ContinuousMatch(42).run(30)
    assert ContinuousMatch(43).run(30)[2] != ContinuousMatch(42).run(30)[2]


def test_every_player_has_continuous_bounded_motion():
    meta, _, frames = prototype()
    ids = set(meta["home"]["starting"] + meta["away"]["starting"])
    assert len(ids) == 22 and len(frames) == 1801
    travelled = dict.fromkeys(ids, 0.0)
    for before, after in zip(frames, frames[1:]):
        assert after["t"] - before["t"] == pytest.approx(0.2)
        assert {p["id"] for p in after["players"]} == ids
        previous = {p["id"]: p for p in before["players"]}
        for p in after["players"]:
            assert 0 <= p["x"] <= 105 and 0 <= p["y"] <= 68
            assert 0 <= p["speed"] <= 8.3
            step = math.dist(absolute(p), absolute(previous[p["id"]]))
            assert step <= 8.3 * 0.2 + 0.003
            travelled[p["id"]] += step
    assert min(travelled.values()) > 10  # goalkeepers and players without events also move


def test_completed_passes_require_receiver_contact():
    _, events, frames = prototype()
    passes = [e for e in events if e["type"] == "pass" and e["outcome"] == "complete"]
    assert len(passes) > 10
    for e in passes:
        frame = frames[round(e["t"] * 5)]
        receiver = next(p for p in frame["players"] if p["id"] == e["receiver_id"])
        end = (e["end_x"], e["end_y"])
        if e["team_id"] == "CAR":
            end = (105 - end[0], 68 - end[1])
        assert math.dist(absolute(receiver), end) <= 1.38


def test_tackles_require_defender_contact_with_ball():
    _, events, frames = prototype()
    tackles = [e for e in events if e["type"] == "tackle"]
    assert tackles
    for e in tackles:
        frame = frames[round(e["t"] * 5)]
        tackler = next(p for p in frame["players"] if p["id"] == e["player_id"])
        assert math.dist(absolute(tackler), (frame["ball"]["x"], frame["ball"]["y"])) < 1.01


def test_events_use_existing_contract_and_intelligence_pipeline():
    meta, events, _ = prototype()
    brain = MatchBrain(meta)
    assert all(a["t"] <= b["t"] for a, b in zip(events, events[1:]))
    for event in events:
        event_adapter.validate_python(event)
        brain.update(event)
    goals = {team: sum(e["type"] == "shot" and e.get("outcome") == "goal" and e.get("team_id") == team for e in events)
             for team in ("POT", "CAR")}
    assert brain.interp.snapshot()["score"] == goals


def test_paused_seek_sends_exact_frame_then_resumes_from_that_position():
    with TestClient(app).websocket_connect("/ws/replay/continuous-prototype?paused=1&at=75.4&speed=5") as ws:
        assert ws.receive_json()["meta"]["tracking"]["hz"] == 5
        assert ws.receive_json()["type"] == "catchup"
        frame = ws.receive_json()
        assert frame["type"] == "frame" and frame["t"] == 75.4 and len(frame["players"]) == 22
        ready = ws.receive_json()
        assert ready["type"] == "ready" and ready["duration"] == 360
        ws.send_json({"cmd": "resume"})
        following = ws.receive_json()
        assert following["type"] == "frame" and 75.4 <= following["t"] <= 76


def test_simulation_listing_and_end_seek():
    client = TestClient(app)
    assert any(m.get("tracking") and m["name"] == "continuous-prototype" for m in client.get("/api/matches").json())
    assert client.get("/api/matches/continuous-prototype").json()["tracking"]["duration"] == 360
    with client.websocket_connect("/ws/replay/continuous-prototype?at=9999&speed=5") as ws:
        messages = []
        while True:
            message = ws.receive_json()
            messages.append(message)
            if message["type"] == "end":
                break
        assert next(m for m in messages if m["type"] == "frame")["t"] == 360
        assert any(m["type"] == "event" and m["event"].get("state") == "full_time" for m in messages)
