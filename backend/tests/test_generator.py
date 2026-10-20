import asyncio
import json

import pytest

from pitch_insights.events.schema import EVENT_TYPES, MatchMeta, event_adapter
from pitch_insights.generator.engine import simulate
from pitch_insights.generator.io import read_match, write_match
from pitch_insights.generator.players import load_clubs
from pitch_insights.generator.script import script_from_dict
from pitch_insights.generator.stream import Replay, match_seconds


@pytest.fixture(scope="module")
def match():
    return simulate(7, "POT", "CAR")


def test_same_seed_same_match(match):
    again = simulate(7, "POT", "CAR")
    assert json.dumps(match, sort_keys=True) == json.dumps(again, sort_keys=True)


def test_different_seed_different_match(match):
    other = simulate(8, "POT", "CAR")
    assert other[1] != match[1]


def test_every_event_passes_schema(match):
    meta, events, _ = match
    MatchMeta.model_validate(meta)
    for ev in events:
        event_adapter.validate_python(ev)
        assert ev["type"] in EVENT_TYPES


def test_seq_and_clock_always_go_up(match):
    _, events, _ = match
    assert [e["seq"] for e in events] == list(range(1, len(events) + 1))
    times = match_seconds(events)
    assert all(a <= b for a, b in zip(times, times[1:]))
    assert [e["period"] for e in events] == sorted(e["period"] for e in events)


def test_match_starts_and_ends_properly(match):
    _, events, _ = match
    states = [e["state"] for e in events if e["type"] == "match_state"]
    assert states == ["kickoff", "half_time", "kickoff", "full_time"]
    assert events[0]["state"] == "kickoff" and events[-1]["state"] == "full_time"


def test_full_length_match(match):
    _, events, _ = match
    assert 1500 <= len(events) <= 2400
    p2 = [e for e in events if e["period"] == 2]
    assert p2[-1]["minute"] == 90 and p2[-1]["t"] >= 2700


def test_lineups_change_only_through_subs(match):
    meta, events, _ = match
    on_pitch = {meta["home"]["id"]: set(meta["home"]["starting"]), meta["away"]["id"]: set(meta["away"]["starting"])}
    subs = {meta["home"]["id"]: 0, meta["away"]["id"]: 0}
    for ev in events:
        team = ev.get("team_id")
        if ev["type"] == "substitution":
            assert ev["player_off_id"] in on_pitch[team]
            assert ev["player_on_id"] not in on_pitch[team]
            on_pitch[team].remove(ev["player_off_id"])
            on_pitch[team].add(ev["player_on_id"])
            subs[team] += 1
            continue
        if "player_id" in ev:
            assert ev["player_id"] in on_pitch[team], (ev["seq"], ev["player_id"])
        if ev["type"] == "foul" and ev["card"] == "red":
            on_pitch[team].remove(ev["player_id"])
    assert all(n <= 5 for n in subs.values())


def test_players_and_ids(match):
    meta, _, _ = match
    for side in ("home", "away"):
        team = meta[side]
        assert len(team["starting"]) == 11 and len(team["bench"]) <= 9
        assert not set(team["starting"]) & set(team["bench"])
        assert all(p["id"].startswith(team["id"] + "-") for p in team["players"])
    assert meta["match"]["id"] == "SYN-7"


def test_debug_values_stay_out_of_meta(match):
    meta, _, debug = match
    for side in ("home", "away"):
        for p in meta[side]["players"]:
            assert "form" not in p
    assert "script" not in meta
    assert set(debug["form"]) == {"POT", "CAR"}


def test_forced_red_card():
    script = script_from_dict({"forced": [{"minute": 30, "type": "red_card", "team": "CAR"}]})
    _, events, _ = simulate(11, "POT", "CAR", script)
    reds = [e for e in events if e["type"] == "foul" and e["card"] == "red" and e["team_id"] == "CAR"]
    assert reds and reds[0]["minute"] >= 30


def test_forced_substitution():
    script = script_from_dict({"forced": [{"minute": 20, "type": "substitution", "team": "POT"}]})
    _, events, _ = simulate(12, "POT", "CAR", script)
    first = next(e for e in events if e["type"] == "substitution" and e["team_id"] == "POT")
    assert first["period"] == 1 and first["minute"] >= 20


def test_all_clubs_play():
    clubs = sorted(load_clubs())
    assert len(clubs) == 4
    for i, home in enumerate(clubs):
        away = clubs[(i + 1) % 4]
        _, events, _ = simulate(100 + i, home, away)
        assert events[-1]["state"] == "full_time"


def test_file_round_trip(match, tmp_path):
    meta, events, debug = match
    path = write_match(tmp_path, meta, events, debug)
    meta2, events2 = read_match(path)
    assert meta2 == meta and events2 == events
    assert (tmp_path / "SYN-7.debug.json").exists()


def test_replay_releases_events_in_order_and_seeks(match):
    _, events, _ = match

    async def collect(replay, limit):
        out = []
        async for ev in replay:
            out.append(ev)
            if len(out) >= limit:
                break
        return out

    fast = Replay(events, speed=1e6, poll=0.001)
    got = asyncio.run(collect(fast, 50))
    assert [e["seq"] for e in got] == list(range(1, 51))

    second_half = match_seconds(events)[next(i for i, e in enumerate(events) if e["period"] == 2)]
    seek = Replay(events, speed=1e6, poll=0.001, start_at=second_half + 1)
    first = asyncio.run(collect(seek, 1))[0]
    assert first["period"] == 2


def test_replay_never_runs_ahead(match):
    _, events, _ = match
    replay = Replay(events, speed=1.0, poll=0.01)

    async def first_two():
        out = []
        async for ev in replay:
            out.append(ev)
            if len(out) == 2:
                break
        return out

    got = asyncio.run(asyncio.wait_for(first_two(), timeout=5))
    assert all(match_seconds(events)[e["seq"] - 1] <= replay.now + 1e-6 for e in got)
