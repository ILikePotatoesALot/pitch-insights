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


def test_bad_speed_and_from_values_are_handled():
    with client.websocket_connect("/ws/replay/comeback-POT-CAR?speed=0&from=abc") as ws:
        assert ws.receive_json()["type"] == "meta"
        msg = ws.receive_json()
        assert msg["type"] == "event" and msg["event"]["seq"] == 1  # "from=abc" starts at kick-off
        ws.send_json({"cmd": "speed", "value": "fast"})  # ignored, not fatal
        ws.send_text("not json")
        ws.send_json({"cmd": "speed", "value": 600})
        assert ws.receive_json()["type"] in ("event", "moment", "state")


def test_disconnect_while_paused_ends_the_replay():
    import time

    with client.websocket_connect("/ws/replay/comeback-POT-CAR?speed=1") as ws:
        ws.receive_json()
        ws.send_json({"cmd": "pause"})
    time.sleep(0.3)  # the server side must have finished; TestClient would hang on exit otherwise


def test_moments_carry_stored_commentary():
    with client.websocket_connect("/ws/replay/comeback-POT-CAR?speed=600&from=87") as ws:
        meta = ws.receive_json()
        assert meta["commentary"]["ai_generated"] is True and meta["commentary"]["model"]
        live = []
        while (msg := ws.receive_json())["type"] != "end":
            if msg["type"] == "catchup":
                shown = [m for m in msg["moments"] if m["tier"] != "minor"]
                assert shown and all(m["commentary"]["casual"] for m in shown)
            if msg["type"] == "moment":
                live.append(msg["moment"])
    goals = [m for m in live if m["type"] == "goal"]
    assert goals and all(m["commentary"]["agent"] == "explainer" for m in goals)
    assert all("commentary" not in m for m in live if m["tier"] == "minor")
