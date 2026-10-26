import pytest
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


def test_comparison_viewer_waits_for_the_shared_start():
    import time

    with client.websocket_connect("/ws/replay/comeback-POT-CAR?speed=600&from=87&paused=1") as ws:
        assert ws.receive_json()["type"] == "meta"
        assert ws.receive_json()["type"] == "catchup"
        ready = ws.receive_json()
        assert ready["type"] == "ready" and ready["kind"] == "synthetic"
        assert abs(ready["server_time"] - time.time()) < 2
        ws.send_json({"cmd": "resume", "wall": ready["server_time"] + 0.4})
        while (message := ws.receive_json())["type"] != "event":
            assert message["type"] in ("state", "cue", "cue_end")
        assert message["event"]["minute"] >= 88


def test_a_replay_from_kick_off_opens_with_the_starting_xi_at_their_opening_rating():
    with client.websocket_connect("/ws/replay/comeback-POT-CAR?speed=0") as ws:
        meta = ws.receive_json()
        assert meta["type"] == "meta"
        first = ws.receive_json()  # before any event, so the ratings panel isn't empty until a minute of play
        assert first["type"] == "state"
        players = first["state"]["players"]
        starters = [pid for side in ("home", "away") for pid in meta["meta"][side]["starting"]]
        assert sorted(p["player_id"] for p in players) == sorted(starters)
        assert {p["rating"] for p in players} == {6.0} and all(p["on_pitch"] for p in players)
        assert ws.receive_json()["type"] == "event"


def test_bad_speed_and_from_values_are_handled():
    with client.websocket_connect("/ws/replay/comeback-POT-CAR?speed=0&from=abc") as ws:
        assert ws.receive_json()["type"] == "meta"
        assert ws.receive_json()["type"] == "state"
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


def test_a_connection_cancelled_while_its_tasks_wind_down_ends_quietly():
    """Starlette ends a connection by cancelling its handler through an anyio cancel scope, which absorbs only
    its own cancellation. If that lands while the handler waits for its other task to stop, the error must still be
    anyio's: asyncio.gather used to raise the task's own CancelledError instead, which escaped (flaky tests in CI)."""
    import asyncio

    import anyio

    from pitch_insights.director.session import run_until_first_done

    async def quick():
        return

    async def slow_to_stop():  # takes 0.2 s to stop, then ends cancelled with its own (plain) CancelledError
        try:
            await anyio.sleep_forever()
        except asyncio.CancelledError:
            loop = asyncio.get_running_loop()
            end = loop.time() + 0.2
            while (left := end - loop.time()) > 0:
                try:
                    await asyncio.sleep(left)
                except asyncio.CancelledError:
                    pass
            raise asyncio.CancelledError() from None

    async def main():
        with anyio.move_on_after(0.1) as scope:
            await run_until_first_done(quick(), slow_to_stop())
        return scope.cancelled_caught

    assert anyio.run(main)


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


def test_stale_commentary_is_not_shown():
    from pitch_insights.agents.prompts import input_hash
    from pitch_insights.server import with_commentary

    meta = client.get("/api/matches/comeback-POT-CAR").json()
    moment = {"id": "M-1", "type": "goal", "clock": "1'", "tier": "headline", "headline": "A goal", "facts": []}
    good = {"moments": {"M-1": {"input_hash": input_hash(moment, meta), "casual": "c"}}}
    stale = {"moments": {"M-1": {"input_hash": "written-for-other-facts", "casual": "c"}}}
    assert with_commentary(moment, good, meta)["commentary"]["casual"] == "c"
    assert "commentary" not in with_commentary(moment, stale, meta)


def test_replay_adds_memory_from_stored_vectors():
    with client.websocket_connect("/ws/replay/comeback-POT-CAR?speed=600&from=89") as ws:
        while (msg := ws.receive_json())["type"] != "catchup":
            pass
    m = next(m for m in msg["moments"] if m["id"] == "M-23")  # Madekuta's second goal, at 61'
    assert any(f["kind"] == "memory" and f["value"].get("moment_id") for f in m["facts"])


def test_reconnect_at_match_seconds_stays_in_first_half_stoppage_time():
    """A language change in first-half stoppage time reconnects at the same second. `from` is a
    broadcast minute, where anything over 45 means the second half, so it can't say 45+2."""
    from pitch_insights.generator.io import read_match
    from pitch_insights.server import SAMPLES

    _, events = read_match(SAMPLES / "comeback-POT-CAR.jsonl")
    first_half_end = max(e["t"] for e in events if e["period"] == 1)
    at = first_half_end - 60
    assert at > 45 * 60  # the sample has stoppage time, so this is after 45:00
    with client.websocket_connect(f"/ws/replay/comeback-POT-CAR?speed=0&at={at}") as ws:
        assert ws.receive_json()["type"] == "meta"
        catchup = ws.receive_json()
        assert catchup["type"] == "catchup" and catchup["state"]["period"] == 1
        assert catchup["state"]["match_minute"] > 45  # not rewound to 45:00
        first = ws.receive_json()
        assert first["type"] == "event" and first["event"]["period"] == 1 and first["event"]["t"] >= at


def test_a_bad_at_value_falls_back_to_from():
    with client.websocket_connect("/ws/replay/comeback-POT-CAR?speed=0&from=abc&at=soon") as ws:
        assert ws.receive_json()["type"] == "meta"
        assert ws.receive_json()["type"] == "state"  # kick-off: the starting XI, then the first event
        assert ws.receive_json()["event"]["seq"] == 1


def test_replay_streams_overlay_cues_that_keep_the_screen_clean():
    from fastapi import WebSocketDisconnect

    from pitch_insights.director import CARD_TEMPLATES, DEFAULT_RULES

    on_screen: dict[str, dict] = {}
    cues, goal_moments, ended = [], set(), False

    def watch(msg):
        c = msg["cue"] if msg["type"] == "cue" else None
        if c:
            cues.append(c)
            on_screen[c["id"]] = c
        elif msg["type"] == "cue_end":
            assert on_screen.pop(msg["id"])  # only ends a cue that is up
            assert msg["reason"] in ("expired", "preempted")
        by_template = [c["template"] for c in on_screen.values()]
        assert len(by_template) == len(set(by_template)) <= DEFAULT_RULES.max_total
        assert sum(t in CARD_TEMPLATES for t in by_template) <= DEFAULT_RULES.max_cards

    with client.websocket_connect("/ws/replay/comeback-POT-CAR?speed=600&from=87") as ws:
        while not ended:
            msg = ws.receive_json()
            ended = msg["type"] == "end"
            if msg["type"] == "catchup":
                assert not any(k.startswith("cue") for k in msg)  # a seek starts with a clear screen
            if msg["type"] == "moment" and msg["moment"]["type"] == "goal":
                goal_moments.add(msg["moment"]["id"])
            watch(msg)
        # After the final whistle the connection stays open until the last cues are down.
        with pytest.raises(WebSocketDisconnect):
            while True:
                watch(ws.receive_json())
    assert {c["moment_id"] for c in cues if c["template"] == "lower_third"} >= goal_moments and len(goal_moments) >= 2
    assert all(isinstance(c["data"], dict) and c["duration"] > 0 for c in cues)
    assert on_screen == {}


def test_cue_text_follows_the_chosen_language():
    def goal_cue(lang):
        with client.websocket_connect(f"/ws/replay/comeback-POT-CAR?speed=600&from=87&lang={lang}") as ws:
            while (msg := ws.receive_json())["type"] != "end":
                if msg["type"] == "cue" and msg["cue"]["template"] == "lower_third" and msg["cue"]["data"]["kind"] == "goal":
                    return msg["cue"]["data"]

    english, german = goal_cue("en"), goal_cue("de")
    assert english["headline"] and german["headline"] and english["headline"] != german["headline"]


def test_a_casual_viewer_is_sent_only_the_cues_made_for_everyone():
    with client.websocket_connect("/ws/replay/comeback-POT-CAR?speed=60&from=87") as ws:
        assert ws.receive_json()["type"] == "meta"
        ws.send_json({"cmd": "detail", "value": "casual"})
        ws.send_json({"cmd": "detail", "value": "nonsense"})  # ignored, not fatal
        cues = []
        while len(cues) < 2:
            msg = ws.receive_json()
            assert msg["type"] != "end"
            if msg["type"] == "cue":
                cues.append(msg["cue"])
    assert all(c["detail"] == "casual" for c in cues)


def test_switching_to_casual_takes_down_the_analyst_cues_on_screen():
    with client.websocket_connect("/ws/replay/comeback-POT-CAR?speed=60&from=80") as ws:
        assert ws.receive_json()["type"] == "meta"
        analyst_up = None
        for _ in range(2000):
            msg = ws.receive_json()
            assert msg["type"] != "end"
            if msg["type"] == "cue" and msg["cue"]["detail"] == "analyst":
                analyst_up = msg["cue"]["id"]
                break
        assert analyst_up, "no analyst cue turned up"
        ws.send_json({"cmd": "detail", "value": "casual"})
        for _ in range(2000):
            msg = ws.receive_json()
            if msg["type"] == "cue_end" and msg["id"] == analyst_up:
                assert msg["reason"] == "withdrawn"
                return
    raise AssertionError("the analyst cue stayed up")


def test_lists_clubs_with_their_squads():
    clubs = client.get("/api/clubs").json()
    assert [c["id"] for c in clubs] == ["BRO", "CAR", "CAU", "POT"]  # by name
    pot = next(c for c in clubs if c["id"] == "POT")
    assert pot["name"] == "Potato FC" and len(pot["players"]) == 20
    assert set(pot["players"][0]) == {"id", "name", "number", "position"}


def test_the_profile_comes_with_the_connection_and_is_sent_back_as_applied():
    with client.websocket_connect("/ws/replay/comeback-POT-CAR?speed=0&mode=casual&team=pot&player=POT-11&focus=xg") as ws:
        meta = ws.receive_json()
    assert meta["profile"] == {"mode": "casual", "team_id": "POT", "player_id": "POT-11", "focus": "xg"}


def test_a_bad_profile_is_ignored_not_fatal():
    url = "/ws/replay/comeback-POT-CAR?speed=0&mode=%00&team=BRO&player=../x&focus=" + "z" * 4000
    with client.websocket_connect(url) as ws:
        meta = ws.receive_json()
        assert meta["profile"] == {"mode": "analyst", "team_id": None, "player_id": None, "focus": None}
        assert ws.receive_json()["type"] == "state"
        assert ws.receive_json()["type"] == "event"


def test_the_favourite_players_goal_alert_reaches_a_casual_fan():
    with client.websocket_connect("/ws/replay/comeback-POT-CAR?speed=600&from=59&mode=casual&player=POT-11") as ws:
        alerts = []
        while (msg := ws.receive_json())["type"] != "end":
            if msg["type"] == "cue" and msg["cue"]["template"] == "fan_alert":
                alerts.append(msg["cue"])
    assert [(a["data"]["event"], a["data"]["clock"], a["why"]) for a in alerts] == [("goal", "61'", "favourite_player")]


def test_two_viewers_of_one_match_are_offered_different_cues():
    def cue_kinds(query):
        out = []
        with client.websocket_connect(f"/ws/replay/comeback-POT-CAR?speed=600&from=59&{query}") as ws:
            while (msg := ws.receive_json())["type"] != "end":
                if msg["type"] == "cue":
                    out.append((msg["cue"]["template"], msg["cue"]["about"]["team_id"]))
        return out

    assert cue_kinds("mode=casual&team=POT&player=POT-11&lang=de") != cue_kinds("mode=analyst&team=CAR&lang=en")
