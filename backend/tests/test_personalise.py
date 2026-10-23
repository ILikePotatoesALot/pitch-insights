"""Personalise: profile parsing and validation, the favourite boost, alerts for the favourite player, the relevance
filter, the focus metric, and determinism. Hand-made cues for the rules; the comeback sample for the rest
(POT-11 scores at 1' and 61' from POT-07's passes; CAR-10 is booked at 47' and scores at 88'; CAR-05 has rating
moments; CAR-11 is booked at 18')."""

from pathlib import Path

import pytest

from pitch_insights.director import CueBuilder, Director, Personaliser, Profile, parse_profile, visible_to
from pitch_insights.director.cues import cue
from pitch_insights.director.personalise import FOCUS_METRICS, MAX_PARAM
from pitch_insights.director.sheet import cue_sheet
from pitch_insights.explain.moments import MatchBrain
from pitch_insights.generator.io import read_match
from pitch_insights.server import state_message

SAMPLES = Path(__file__).resolve().parents[2] / "samples"
META, EVENTS = read_match(SAMPLES / "comeback-POT-CAR.jsonl")


def make(template="stat_card", priority=50, team_id="POT", player_id=None, detail="casual", **kw):
    return cue(template, 0.0, 6.0, priority, tier="notable", detail=detail, moment_id=kw.pop("moment_id", "M-1"),
               data=kw.pop("data", {}), team_id=team_id, player_id=player_id)


def personaliser(**kw):
    return Personaliser(Profile(**kw), META)


def sheet(profile=None, detail="analyst", pace=20.0):
    return cue_sheet(META, EVENTS, pace=pace, profile=profile, detail=detail)


def shown(entries):
    return [e["message"]["cue"] for e in entries if e["message"]["type"] == "cue"]


# ---------------------------------------------------------------- profile parsing and validation

def test_a_good_profile_is_read_as_given():
    p = parse_profile({"mode": "casual", "team": "POT", "player": "POT-11", "focus": "xg"}, META)
    assert p == Profile("casual", "POT", "POT-11", "xg")
    assert p.public() == {"mode": "casual", "team_id": "POT", "player_id": "POT-11", "focus": "xg"}


def test_no_parameters_gives_the_default_profile():
    assert parse_profile({}, META) == Profile() == Profile("analyst", None, None, None)


def test_case_and_spaces_are_forgiven():
    assert parse_profile({"mode": " CASUAL ", "team": "pot", "player": "pot-11", "focus": "XG"}, META) \
        == Profile("casual", "POT", "POT-11", "xg")


@pytest.mark.parametrize("params", [
    {"mode": "expert", "team": "XXX", "player": "NOBODY", "focus": "vibes"},        # unknown values
    {"mode": "", "team": "", "player": " ", "focus": ""},                           # empty
    {"mode": "x" * 5000, "team": "P" * 5000, "player": "9" * 5000, "focus": "z" * 5000},  # junk of any length
    {"mode": None, "team": 3, "player": ["POT-11"], "focus": {"a": 1}},             # not strings at all
    {"team": "BRO", "player": "BRO-09"},                                            # real, but not in this match
    {"mode": "casual; DROP TABLE", "team": "POT'--", "player": "../../etc", "focus": "xg; 1=1"},
])
def test_bad_input_is_ignored_and_never_raises(params):
    assert parse_profile(params, META) == Profile()


def test_each_choice_is_checked_on_its_own():
    p = parse_profile({"mode": "casual", "team": "XXX", "player": "CAR-10", "focus": "nope"}, META)
    assert p == Profile("casual", None, "CAR-10", None)  # the good choices stand, the bad ones fall away


def test_a_value_just_over_the_length_cap_is_ignored():
    assert parse_profile({"team": "P" * (MAX_PARAM + 1)}, META).team_id is None


def test_every_focus_metric_is_known_to_the_server():
    for key in FOCUS_METRICS:
        assert parse_profile({"focus": key}, META).focus == key


# ---------------------------------------------------------------- no profile, no change

def test_without_favourites_or_focus_nothing_changes():
    p = personaliser()
    assert not p.active
    c = make("rating_alert", 40, team_id="CAR", player_id="CAR-05")
    assert p.adjust(c, None) == c


def test_the_neutral_sheet_is_the_one_the_director_always_made():
    assert sheet() == sheet(profile=Profile()) == sheet(profile=Profile(mode="analyst"))


# ---------------------------------------------------------------- boost

def test_cues_about_the_favourite_club_gain_priority_and_say_why():
    c = personaliser(team_id="POT").adjust(make("stat_card", 50, "POT"), None)
    assert c["priority"] == 60 and c["why"] == "favourite_club"


def test_cues_about_the_favourite_player_gain_more_than_the_club():
    p = personaliser(team_id="POT", player_id="POT-11")
    c = p.adjust(make("rating_alert", 50, "POT", "POT-11"), None)
    assert c["priority"] == 70 and c["why"] == "favourite_player"


def test_other_cues_are_left_alone():
    c = make("stat_card", 50, "CAR")
    assert personaliser(team_id="POT").adjust(c, None) == c


def test_a_boost_never_turns_a_story_cue_into_an_urgent_one():
    urgent = Director().rules.urgent
    c = personaliser(team_id="POT", player_id="POT-11").adjust(make("lower_third", 85, "POT", "POT-11"), None)
    assert c["priority"] == urgent - 1
    goal = make("lower_third", 95, "POT", "POT-11")  # already urgent: not lowered, not raised
    assert personaliser(team_id="POT").adjust(goal, None)["priority"] == 95


def test_adjusting_never_changes_the_cue_it_was_given():
    c = make("stat_card", 50, "POT", data={"rows": [{"key": "shots", "home": 1, "away": 2}]})
    before = repr(c)
    personaliser(team_id="POT", focus="xg").adjust(c, {"teams": {"POT": {"xg": 1.0}, "CAR": {"xg": 0.5}}})
    assert repr(c) == before


def test_the_player_of_a_favourite_club_alone_counts_as_their_side():
    p = personaliser(player_id="POT-11")  # no club chosen: Potato is their side
    assert p.side == "POT"
    assert p.adjust(make("stat_card", 50, "POT"), None)["why"] == "favourite_club"
    assert p.adjust(make("rating_alert", 40, "CAR", "CAR-05"), None) is None


def test_a_boosted_cue_pre_empts_a_rival_it_would_not_have_beaten():
    boosted = personaliser(team_id="POT").adjust(make("stat_card", 52, "POT"), None)  # 52 -> 62
    rival = make("stat_card", 52, "CAR")
    d = Director()
    d.offer([rival], now=0.0)
    out = d.offer([boosted], now=3.0)  # 62 beats 52 by 10, once the rival has had its hold
    assert [m["reason"] for m in out if m["type"] == "cue_end"] == ["preempted"]
    d2 = Director()
    d2.offer([rival], now=0.0)
    assert [m for m in d2.offer([make("stat_card", 52, "POT")], now=3.0) if m["type"] == "cue_end"] == []  # unboosted


# ---------------------------------------------------------------- relevance

def test_rating_alerts_and_speed_popups_about_the_other_side_are_dropped():
    p = personaliser(team_id="POT")
    assert p.adjust(make("rating_alert", 40, "CAR", "CAR-05"), None) is None
    assert p.adjust(make("speed_popup", 35, "CAR", "CAR-05"), None) is None


def test_the_other_sides_story_cards_and_lower_thirds_still_come():
    p = personaliser(team_id="POT")
    for template in ("lower_third", "stat_card", "player_tag"):
        assert p.adjust(make(template, 60, "CAR", "CAR-05" if template == "player_tag" else None), None)


def test_the_favourite_players_own_cards_are_never_dropped_even_on_the_other_side():
    p = personaliser(team_id="POT", player_id="CAR-05")  # a Potato fan who likes a Carrot player
    assert p.adjust(make("rating_alert", 40, "CAR", "CAR-05"), None)["why"] == "favourite_player"


def test_urgent_cues_always_come():
    p = personaliser(team_id="POT")
    assert p.adjust(make("rating_alert", 90, "CAR", "CAR-05"), None)


def test_a_viewer_without_a_side_loses_nothing():
    c = make("rating_alert", 40, "CAR", "CAR-05")
    assert personaliser(focus="xg").adjust(c, None) == c


# ---------------------------------------------------------------- focus metric

STATE = {"teams": {"POT": {"xg": 1.234, "xt_added": 2.0, "possession_pct": 55, "shots": 5, "pass_accuracy_pct": 80},
                   "CAR": {"xg": 0.5, "xt_added": 1.0, "possession_pct": 45, "shots": 2, "pass_accuracy_pct": 70}},
         "win_probability": {"home": 0.5, "draw": 0.25, "away": 0.25}}
ROWS = [{"key": "possession_pct", "home": 55, "away": 45}, {"key": "shots", "home": 5, "away": 2}]


def test_a_stat_card_leads_with_the_focus_metric_marked_as_such():
    c = personaliser(focus="xg").adjust(make("stat_card", data={"kind": "control", "rows": ROWS}), STATE)
    assert c["data"]["rows"][0] == {"key": "xg", "home": 1.23, "away": 0.5, "focus": True}
    assert [r["key"] for r in c["data"]["rows"]] == ["xg", "possession_pct", "shots"]


def test_a_metric_the_card_already_has_is_moved_to_the_front_not_repeated():
    c = personaliser(focus="shots").adjust(make("stat_card", data={"kind": "control", "rows": ROWS}), STATE)
    assert [r["key"] for r in c["data"]["rows"]] == ["shots", "possession_pct"] and c["data"]["rows"][0]["focus"]


def test_win_probability_is_a_focus_row_in_percent():
    c = personaliser(focus="win_probability").adjust(make("stat_card", data={"rows": []}), STATE)
    assert c["data"]["rows"] == [{"key": "win_probability", "home": 50, "away": 25, "focus": True}]


@pytest.mark.parametrize("key", FOCUS_METRICS)
def test_every_focus_metric_makes_a_row_from_the_real_state(key):
    brain = MatchBrain(META)
    for ev in EVENTS[:400]:
        brain.update(ev)
    state = state_message(brain)
    row = personaliser(focus=key)._row(key, state)
    assert row["key"] == key and row["home"] is not None and row["away"] is not None


def test_focus_leaves_other_templates_alone():
    c = make("lower_third", data={"rows": ROWS})
    assert personaliser(focus="xg").adjust(c, STATE)["data"] == {"rows": ROWS}


# ---------------------------------------------------------------- alerts for the favourite

def alerts_for(player):
    return [c for c in shown(sheet(Profile("casual", None, player), detail="casual")) if c["template"] == "fan_alert"]


def test_the_favourite_scorer_gets_a_goal_alert_with_their_live_numbers():
    goals = [c for c in alerts_for("POT-11") if c["data"]["event"] == "goal"]
    assert [c["data"]["clock"] for c in goals] == ["1'", "61'"]
    last = goals[-1]
    assert last["priority"] >= 90 and last["why"] == "favourite_player" and last["detail"] == "casual"
    assert last["about"] == {"team_id": "POT", "player_id": "POT-11"}
    assert last["data"]["goals"] == 2 and isinstance(last["data"]["rating"], float) and last["data"]["name"]


def test_the_favourite_passer_gets_an_assist_alert_on_the_scorers_goal():
    assists = [c for c in alerts_for("POT-07") if c["data"]["event"] == "assist"]
    assert [c["data"]["clock"] for c in assists] == ["1'", "61'"]
    assert all(c["about"]["player_id"] == "POT-07" and c["priority"] < 90 for c in assists)


def test_a_booking_is_an_alert_though_it_makes_no_moment():
    booked = [c for c in alerts_for("CAR-11") if c["data"]["event"] == "yellow_card"]
    assert [c["data"]["clock"] for c in booked] == ["18'"] and isinstance(booked[0]["data"]["rating"], float)


def test_a_rating_change_is_an_alert_and_replaces_the_analyst_only_rating_alert():
    shown_cues = shown(sheet(Profile("analyst", None, "CAR-05"), detail="analyst"))
    mine = [c for c in shown_cues if c["about"]["player_id"] == "CAR-05"]
    assert {c["template"] for c in mine} <= {"fan_alert", "lower_third", "player_tag"}  # no rating_alert beside it
    kinds = {c["data"]["event"] for c in mine if c["template"] == "fan_alert"}
    assert kinds and kinds <= {"rating_up", "rating_down", "rating_milestone"}


def test_the_alert_replaces_the_generic_player_tag_for_the_favourites_own_goal():
    cues = shown(sheet(Profile("casual", None, "POT-11"), detail="casual"))
    first_goal = [c for c in cues if c["moment_id"] == next(c2["moment_id"] for c2 in cues if c2["template"] == "fan_alert")]
    assert {c["template"] for c in first_goal} >= {"fan_alert", "lower_third"} and "player_tag" not in {c["template"] for c in first_goal}
    plain = shown(sheet(Profile("casual"), detail="casual"))
    assert "player_tag" in {c["template"] for c in plain if c["moment_id"] == first_goal[0]["moment_id"]}


def test_a_scorers_tag_stays_when_it_is_only_the_assist_that_is_favourite():
    tags = [c for c in shown(sheet(Profile("casual", None, "POT-07"), detail="casual")) if c["template"] == "player_tag"]
    assert any(c["about"]["player_id"] == "POT-11" for c in tags)


def test_alerts_are_for_everyone_so_casual_fans_get_them():
    assert alerts_for("POT-11") and all(visible_to(c, "casual") for c in alerts_for("POT-11"))


def test_no_favourite_player_means_no_alerts():
    assert not [c for c in shown(sheet(Profile("casual", "POT"), detail="casual")) if c["template"] == "fan_alert"]


def test_a_player_who_does_nothing_notable_gets_no_alerts():
    quiet = next(p["id"] for p in META["home"]["players"] if p["position"] == "GK")
    assert alerts_for(quiet) == []


# ---------------------------------------------------------------- determinism and the screen rules

PROFILES = [Profile("casual", "POT", "POT-11", "xg"), Profile("analyst", "CAR", "CAR-10", "xt_added"),
            Profile("casual", None, "CAR-05", "win_probability")]


@pytest.mark.parametrize("profile", PROFILES)
def test_the_same_profile_replays_the_same_cues(profile):
    assert sheet(profile, detail=profile.mode) == sheet(profile, detail=profile.mode)


def test_different_profiles_give_clearly_different_screens():
    fan = shown(sheet(PROFILES[0], detail="casual"))
    analyst = shown(sheet(PROFILES[1], detail="analyst"))
    assert fan != analyst
    assert {c["data"]["event"] for c in fan if c["template"] == "fan_alert"} != \
           {c["data"]["event"] for c in analyst if c["template"] == "fan_alert"}
    assert len(analyst) > len(fan)  # an analyst gets the stats cards and rating alerts a casual fan never sees


@pytest.mark.parametrize("profile", PROFILES)
@pytest.mark.parametrize("pace", [1.0, 20.0, 60.0])
def test_personalised_screens_still_obey_the_clutter_rules(profile, pace):
    rules = Director().rules
    live: dict[str, dict] = {}
    for entry in sheet(profile, detail=profile.mode, pace=pace):
        m = entry["message"]
        if m["type"] == "cue":
            live[m["cue"]["id"]] = m["cue"]
        else:
            live.pop(m["id"])
        templates = [c["template"] for c in live.values()]
        assert len(templates) == len(set(templates)) <= rules.max_total
        assert sum(t != "lower_third" for t in templates) <= rules.max_cards
    assert live == {}


@pytest.mark.parametrize("profile", PROFILES)
def test_every_goal_red_card_and_the_final_whistle_still_reach_a_personalised_screen(profile):
    cues = shown(sheet(profile, detail="casual", pace=60.0))
    kinds = {c["data"].get("kind") for c in cues if c["template"] == "lower_third"}
    assert {"goal", "full_time"} <= kinds
    assert sum(c["data"].get("kind") == "goal" for c in cues if c["template"] == "lower_third") == 5


def test_the_favourite_club_is_shown_more_of_its_own_story_than_a_neutral_viewer():
    def tally(profile):
        cues = shown(sheet(profile, detail="analyst"))
        return sum(1 for c in cues if c["about"]["team_id"] == "POT" and c["template"] != "lower_third")
    assert tally(Profile("analyst", "POT")) >= tally(Profile("analyst"))


def test_the_other_sides_rating_alerts_never_take_a_slot_on_a_fans_screen():
    cues = shown(sheet(Profile("analyst", "POT"), detail="analyst"))
    assert not [c for c in cues if c["template"] == "rating_alert" and c["about"]["team_id"] == "CAR"]
    assert [c for c in shown(sheet()) if c["template"] == "rating_alert" and c["about"]["team_id"] == "CAR"]
