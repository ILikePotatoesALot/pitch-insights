from fastapi.testclient import TestClient

from pitch_insights.server import app

client = TestClient(app)


def test_lists_demo_matches():
    matches = client.get("/api/matches").json()
    names = {m["name"] for m in matches}
    assert "comeback-POT-CAR" in names
    assert client.get("/api/matches/comeback-POT-CAR").json()["type"] == "match_meta"
    assert client.get("/api/matches/..%2F..%2Fsecret").status_code == 404


def test_replay_streams_events_moments_and_state():
    seen = {"meta": 0, "event": 0, "moment": 0, "state": 0, "end": 0}
    with client.websocket_connect("/ws/replay/comeback-POT-CAR?speed=600&from=87") as ws:
        while True:
            msg = ws.receive_json()
            seen[msg["type"]] = seen.get(msg["type"], 0) + 1
            if msg["type"] == "catchup":
                assert msg["state"]["score"] == {"POT": 2, "CAR": 1}
                assert any(m["type"] == "goal" for m in msg["moments"])
            if msg["type"] == "end":
                break
            if msg["type"] == "event":
                assert msg["event"]["period"] == 2 and msg["event"]["minute"] >= 88
    assert seen["meta"] == 1 and seen["catchup"] == 1 and seen["event"] > 50 and seen["moment"] >= 2 and seen["state"] >= 1
