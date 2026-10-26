from fastapi.testclient import TestClient

from pitch_insights.generator.io import read_match
from pitch_insights.server import SAMPLES, app, position_events


def test_position_events_keep_latest_actor_and_successful_receiver_positions_in_order():
    events = [
        {"seq": 1, "type": "pass", "team_id": "POT", "player_id": "POT-11", "receiver_id": "POT-07",
         "outcome": "complete", "x": 0, "y": 0, "end_x": 30, "end_y": 40},
        {"seq": 2, "type": "carry", "team_id": "POT", "player_id": "POT-11", "x": 10, "y": 20},
        {"seq": 3, "type": "pass", "team_id": "POT", "player_id": "POT-09", "receiver_id": "POT-07",
         "outcome": "incomplete", "x": 20, "y": 30, "end_x": 80, "end_y": 40},
        {"seq": 4, "type": "foul", "player_id": "POT-07"},
    ]
    assert position_events(events) == events[:3]
    assert position_events([]) == []
    assert position_events(events[:1]) == events[:1]  # the same event can locate both players


def test_catchup_restores_positions_older_than_the_heat_window_without_future_events():
    _, events = read_match(SAMPLES / "comeback-POT-CAR.jsonl")
    at = 26 * 60
    past = [ev for ev in events if ev["period"] == 1 and ev["t"] < at]
    with TestClient(app).websocket_connect(f"/ws/replay/comeback-POT-CAR?speed=0&at={at}&player=POT-07") as ws:
        assert ws.receive_json()["type"] == "meta"
        catchup = ws.receive_json()
    assert catchup["type"] == "catchup"
    restored = catchup["position_events"]
    assert restored == position_events(past)
    assert all(ev in past for ev in restored)
    assert len(restored) <= 40  # bounded by the two squads, rather than the whole match
    recent_ids = {ev["seq"] for ev in catchup["recent_events"]}
    assert any(ev["seq"] not in recent_ids for ev in restored)
    # No old event was added to the heat window to make the spotlight work.
    assert all(ev["type"] == "match_state" or ev["t"] >= past[-1]["t"] - 180
               for ev in catchup["recent_events"])
