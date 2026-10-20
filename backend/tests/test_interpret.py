import json

import pytest

from pitch_insights.generator.engine import simulate
from pitch_insights.generator.script import script_from_dict
from pitch_insights.interpret import xt
from pitch_insights.interpret.interpreter import Interpreter
from pitch_insights.interpret.winprob import prior_rate, win_probability


@pytest.fixture(scope="module")
def match():
    return simulate(7, "POT", "CAR")


def run(meta, events):
    it = Interpreter(meta)
    signals = []
    for e in events:
        signals += it.update(e)
    return it, signals


@pytest.fixture(scope="module")
def played(match):
    meta, events, _ = match
    return run(meta, events)


def test_score_and_counts_match_the_events(match, played):
    meta, events, _ = match
    it, _ = played
    snap = it.snapshot()
    for team in (meta["home"]["id"], meta["away"]["id"]):
        mine = [e for e in events if e.get("team_id") == team]
        assert snap["score"][team] == sum(e["type"] == "shot" and e["outcome"] == "goal" for e in mine)
        assert snap["teams"][team]["passes"] == sum(e["type"] == "pass" for e in mine)
        assert snap["teams"][team]["shots"] == sum(e["type"] == "shot" for e in mine)
    poss = sum(snap["teams"][t]["possession_pct"] for t in snap["teams"])
    assert abs(poss - 100) < 0.2


def test_full_time_win_probability_is_the_result(played):
    it, _ = played
    snap = it.snapshot()
    h, a = snap["score"].values()
    wp = snap["win_probability"]
    expected = "home" if h > a else "away" if a > h else "draw"
    assert wp[expected] == 1.0 and snap["finished"]


def test_never_looks_ahead(match):
    """The state after the first k events is the same whether or not later events exist."""
    meta, events, _ = match
    k = len(events) // 2
    full = Interpreter(meta)
    mid_snapshot = None
    for i, e in enumerate(events):
        full.update(e)
        if i == k - 1:
            mid_snapshot = json.dumps(full.snapshot(), sort_keys=True)
    partial, _ = run(meta, events[:k])
    assert json.dumps(partial.snapshot(), sort_keys=True) == mid_snapshot


def test_same_input_same_output(match, played):
    meta, events, _ = match
    again, sig2 = run(meta, events)
    it, sig1 = played
    assert json.dumps(again.snapshot(), sort_keys=True) == json.dumps(it.snapshot(), sort_keys=True)
    assert sig1 == sig2


def test_ratings_stay_in_range_and_start_at_six(match):
    meta, events, _ = match
    it = Interpreter(meta)
    it.update(events[0])
    assert all(p["rating"] == 6.0 for p in it.snapshot()["players"].values())
    for e in events[1:]:
        it.update(e)
    for p in it.snapshot()["players"].values():
        assert 3.0 <= p["rating"] <= 10.0


def test_rating_breakdown_explains_the_rating(played):
    it, _ = played
    snap = it.snapshot()
    scorers = [p for p in snap["players"].values() if p["goals"]]
    for p in scorers:
        assert "Goals and assists" in p["by_category"]
        assert any(m["label"] == "goal" for m in p["key_moments"])


def test_win_probability_always_sums_to_one(match):
    meta, events, _ = match
    it = Interpreter(meta)
    for e in events:
        it.update(e)
        assert abs(sum(it.wp.values()) - 1) < 1e-3


def test_patterns_in_range(match):
    meta, events, _ = match
    it = Interpreter(meta)
    for i, e in enumerate(events):
        it.update(e)
        if i % 50 == 0:
            p = it.snapshot()["patterns"]
            assert -1 <= p["momentum"] <= 1 and 0 <= p["chaos"] <= 1 and p["tempo"] >= 0
    series = it.snapshot()["momentum_series"]
    assert series[0]["minute"] == 0 and all(-100 <= s["value"] <= 100 for s in series)


def test_goal_signals_carry_win_probability_swing(match, played):
    meta, events, _ = match
    _, signals = played
    goals = [s for s in signals if s["type"] == "goal"]
    assert len(goals) == sum(e["type"] == "shot" and e["outcome"] == "goal" for e in events)
    for g in goals:
        assert {"win_prob_before", "win_prob_after", "win_prob_swing"} <= set(g["data"])
    assert signals[-1]["type"] in ("full_time", "milestone")


def test_red_card_signal_and_ten_men():
    script = script_from_dict({"forced": [{"minute": 30, "type": "red_card", "team": "CAR"}]})
    meta, events, _ = simulate(11, "POT", "CAR", script)
    it, signals = run(meta, events)
    reds = [s for s in signals if s["type"] == "red_card" and s["team_id"] == "CAR"]
    assert reds and reds[0]["data"]["men_left"] == 10
    assert reds[0]["data"]["win_prob_swing"] < 0
    assert it.snapshot()["teams"]["CAR"]["men"] <= 10


def test_events_out_of_order_are_rejected(match):
    meta, events, _ = match
    it = Interpreter(meta)
    it.update(events[0])
    it.update(events[1])
    with pytest.raises(ValueError):
        it.update(events[1])


def test_xt_grid_rises_toward_goal():
    g = xt.grid()
    assert len(g) == xt.COLS and all(len(col) == xt.ROWS for col in g)
    assert xt.value(100, 34) > xt.value(80, 34) > xt.value(20, 34)


def test_win_probability_basics():
    ph, pa = prior_rate(5, True), prior_rate(15, False)
    start = win_probability(0, 0, 0, 0, 0, ph, pa)
    assert start["home"] > start["away"]
    late_lead = win_probability(1, 0, 88, 1.0, 1.0, ph, pa)
    assert late_lead["home"] > 0.85
    down_to_ten = win_probability(0, 0, 30, 0.5, 0.5, ph, pa, men_home=10)
    assert down_to_ten["home"] < win_probability(0, 0, 30, 0.5, 0.5, ph, pa)["home"]


def test_breakdown_adds_up_to_the_rating(played):
    it, _ = played
    for p in it.snapshot()["players"].values():
        assert abs(p["rating"] - 6.0 - sum(p["by_category"].values())) <= 0.1, p["name"]


def test_failed_tackles_do_not_change_possession(match):
    meta, events, _ = match
    it = Interpreter(meta)
    for e in events:
        before = sum(1 for _, k, _, _ in it.patterns.items if k == "possession_change")
        it.update(e)
        after = sum(1 for _, k, _, _ in it.patterns.items if k == "possession_change")
        if e["type"] == "tackle" and e["outcome"] == "lost":
            assert after <= before


def test_rating_changes_are_tracked_for_everyone_affected():
    from pitch_insights.interpret.ratings import Ratings

    r = Ratings({"A-01": "CM", "A-02": "ST", "B-01": "GK"})
    r.add("A-01", 1, "1'", "goals", "assist", 0.6)
    r.add("B-01", 1, "1'", "conceding", "goal conceded", -0.2)
    assert r.pop_changed() == {"A-01", "B-01"}
    assert r.pop_changed() == set()


def test_penalties_are_flagged_on_the_foul():
    import itertools

    from pitch_insights.generator.players import load_clubs

    pairs = list(itertools.permutations(sorted(load_clubs()), 2))
    shots = signals = 0
    for i in range(30):
        meta, events, _ = simulate(700 + i, *pairs[i % len(pairs)])
        _, sig = run(meta, events)
        shots += sum(e["type"] == "shot" and e["kind"] == "penalty" for e in events)
        signals += sum(s["type"] == "penalty_awarded" for s in sig)
        for prev, e in zip(events, events[1:]):
            if e["type"] == "shot" and e["kind"] == "penalty":
                fouls = [f for f in events[:e["seq"] - 1] if f["type"] == "foul"]
                assert fouls[-1]["penalty"] is True
    assert shots > 0 and signals == shots


def test_momentum_series_follows_the_match_clock(played):
    it, _ = played
    series = it.snapshot()["momentum_series"]
    second = [s for s in series if s["period"] == 2]
    assert second[0]["minute"] == 45 and second[-1]["minute"] >= 90
    assert all(s["clock"].endswith("'") for s in series)


def test_report_stops_at_the_requested_minute(match):
    from pitch_insights.interpret.__main__ import stop_index

    _, events, _ = match
    i = stop_index(events, 70)
    assert events[i - 1]["period"] == 2 and events[i - 1]["minute"] <= 70
    assert events[i]["minute"] >= 70
    assert stop_index(events, None) == len(events)
