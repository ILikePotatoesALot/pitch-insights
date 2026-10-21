import json

import pytest

from pitch_insights.explain.moments import HEADLINE, NOTABLE, MatchBrain
from pitch_insights.generator.engine import simulate
from pitch_insights.generator.script import script_from_dict


def run(meta, events):
    brain = MatchBrain(meta)
    for e in events:
        brain.update(e)
    return brain


@pytest.fixture(scope="module")
def match():
    return simulate(7, "POT", "CAR")


@pytest.fixture(scope="module")
def brain(match):
    meta, events, _ = match
    return run(meta, events)


def test_every_goal_is_a_headline(match, brain):
    _, events, _ = match
    goals = sum(e["type"] == "shot" and e["outcome"] == "goal" for e in events)
    goal_moments = [m for m in brain.moments if m["type"] == "goal"]
    assert len(goal_moments) == goals
    assert all(m["tier"] == "headline" for m in goal_moments)


def test_full_time_summary_comes_last(brain):
    last = brain.moments[-1]
    assert last["type"] == "full_time" and last["tier"] == "headline"
    assert any(f["kind"] == "player_of_the_match" for f in last["facts"])


def test_moments_are_well_formed(brain):
    for m in brain.moments:
        assert 0 <= m["importance"] <= 1
        expected = "headline" if m["importance"] >= HEADLINE else "notable" if m["importance"] >= NOTABLE else "minor"
        assert m["tier"] == expected
        assert m["headline"] and m["facts"]
        texts = [f["text"] for f in m["facts"]]
        assert all(t and f["kind"] for t, f in zip(texts, m["facts"]))
        assert len(texts) == len(set(texts)), m["headline"]


def test_goal_evidence_has_the_key_numbers(brain):
    g = next(m for m in brain.moments if m["type"] == "goal")
    kinds = {f["kind"] for f in g["facts"]}
    assert {"score", "win_probability", "chance", "rating", "match_totals"} <= kinds


def test_same_input_same_moments(match, brain):
    meta, events, _ = match
    again = run(meta, events)
    assert json.dumps(again.moments, sort_keys=True) == json.dumps(brain.moments, sort_keys=True)


def test_never_looks_ahead(match, brain):
    meta, events, _ = match
    k = len(events) // 2
    partial = run(meta, events[:k])
    assert partial.moments == brain.moments[:len(partial.moments)]
    assert all(m["seq"] <= events[k - 1]["seq"] for m in partial.moments)


def test_red_card_moment():
    script = script_from_dict({"forced": [{"minute": 30, "type": "red_card", "team": "CAR"}]})
    meta, events, _ = simulate(11, "POT", "CAR", script)
    brain = run(meta, events)
    red = next(m for m in brain.moments if m["type"] == "red_card")
    assert "sent off" in red["headline"] and red["tier"] in ("headline", "notable")
    assert any(f["kind"] == "men" and f["value"] == 10 for f in red["facts"])


def test_goal_moment_absorbs_its_milestones(match, brain):
    """A goal's brace or season milestone is part of the goal moment, not a separate one."""
    _, events, _ = match
    goal_seqs = {m["seq"] for m in brain.moments if m["type"] == "goal"}
    separate = [m for m in brain.moments if m["type"] == "milestone" and m["seq"] in goal_seqs]
    assert not separate
