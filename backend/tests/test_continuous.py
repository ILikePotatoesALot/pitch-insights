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


def force_shot(outcome):
    game = ContinuousMatch()
    keeper = next(r for r in game.runners.values() if r.side == 1 and r.player.role == "GK")
    game.engine.t = 3
    game.flight = dict(kind="shot", start=game.ball, end=keeper.xy, born=1, duration=1,
                       side=0, shooter=game.owner, keeper=keeper, outcome=outcome, xg=0.2)
    game.owner = None
    game.step()
    return game, keeper


def test_a_save_gives_the_keeper_possession_before_distribution():
    game, keeper = force_shot("saved")
    assert game.owner is keeper and game.restart_kind is None
    assert game.frame()["phase"] == "keeper_ball"
    assert game.engine.events[-1]["outcome"] == "saved"
    for _ in range(9):
        game.engine.t = round(game.engine.t + 0.2, 1)
        game.step()
        assert game.owner is keeper
    assert distance_xy(game.ball, keeper.xy) < 0.01


def test_keeper_distributes_before_a_nearby_opponent_can_tackle_the_held_ball():
    game, keeper = force_shot("saved")
    opponent = next(r for r in game.runners.values() if r.side == 0)
    opponent.xy = (keeper.xy[0] - 0.2, keeper.xy[1])
    game.engine.t = game.held_until
    game.step()
    assert game.flight and game.flight["passer"] is keeper
    assert not any(e["type"] == "tackle" for e in game.engine.events)


def test_simulation_commentary_rejects_invented_intentions():
    from pitch_insights.agents.grounding import check
    from pitch_insights.explain.simulation import prototype_moments
    meta = prototype()[0]
    moment = prototype_moments()[0]
    assert "looking to" in check("Looking to open space.", moment, meta).unsupported
    from pitch_insights.agents.grounding import with_hedging
    result = with_hedging(check("Players advance 24 m.", moment, meta), "Players advance 24 m.", "", moment)
    assert any("casual measurements" in problem for problem in result.unsupported)


def distance_xy(a, b):
    return math.dist(a, b)


@pytest.mark.parametrize("outcome,kind", [("goal", "kickoff"), ("off_target", "goal_kick")])
def test_shot_restarts_go_to_the_correct_place_and_side(outcome, kind):
    game, keeper = force_shot(outcome)
    assert game.restart_kind == kind and game.restart_side == 1
    if kind == "goal_kick":
        assert game.restart_taker is keeper
        assert game.restart_point == (100, 34)
    else:
        assert game.restart_point == (52.5, 34)
    for _ in range(180):
        game.engine.t = round(game.engine.t + 0.2, 1)
        game.step()
        if game.flight and game.flight["kind"] == "pass":
            assert game.flight["pass_kind"] == kind
            assert game.flight["passer"].side == 1
            break
    else:
        pytest.fail("restart never released")


def test_kickoff_waits_for_opponents_to_clear_the_centre_circle():
    game = ContinuousMatch()
    game.begin_restart("kickoff", 0)
    game.engine.t = game.restart_until + 1
    game.ball = game.restart_point
    game.restart_taker.xy = game.restart_point
    opponent = next(r for r in game.runners.values() if r.side == 1)
    opponent.xy = (52.5, 35)
    assert not game.restart_ready()


def test_positional_evidence_is_measured_and_excludes_full_match_predictions():
    from pitch_insights.explain.simulation import prototype_moments
    meta, _, frames = prototype()
    for frame in frames:
        for team in (meta["home"], meta["away"]):
            roster = {p["id"]: p for p in team["players"]}
            players = [p for p in frame["players"] if p["team_id"] == team["id"] and roster[p["id"]]["position"] != "GK"]
            width = round(max(p["y"] for p in players) - min(p["y"] for p in players))
            assert frame["analysis"]["teams"][team["id"]]["width"] == width
    moments = prototype_moments()
    assert any(m["type"] == "off_ball_run" for m in moments)
    assert all("win_probability" not in m for m in moments)
    assert all(f["kind"] != "win_probability" for m in moments for f in m["facts"])
    assert all(not f["kind"].startswith(("season_", "career_")) for m in moments for f in m["facts"])
    for m in moments:
        if m["type"] == "off_ball_run":
            end = frames[int(m["match_time"] * 5)]
            start = frames[int((m["match_time"] - 4) * 5)]
            pid = m["player_id"]
            assert next(p for p in end["players"] if p["id"] == pid)["x"] - next(p for p in start["players"] if p["id"] == pid)["x"] >= 8


def test_replay_sends_positional_moments_once_and_no_exhibition_win_prediction():
    with TestClient(app).websocket_connect("/ws/replay/continuous-prototype?at=358&speed=600") as ws:
        messages = []
        while True:
            message = ws.receive_json()
            messages.append(message)
            if message["type"] == "end":
                break
    catchup = next(m for m in messages if m["type"] == "catchup")
    assert catchup["state"]["win_probability"] is None
    ids = [m["id"] for m in catchup["moments"]] + [m["moment"]["id"] for m in messages if m["type"] == "moment"]
    assert len(ids) == len(set(ids))
    assert any(m["type"] == "frame" and "analysis" in m for m in messages)


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
