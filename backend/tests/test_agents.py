"""Agents: groundedness check, the commentary desk's retry and fallback paths, settings and
stored commentary. No network: the writer is a fake."""

import asyncio
from pathlib import Path

import httpx
import openai
import pytest

from pitch_insights.agents import grounding
from pitch_insights.agents.clients import base_url
from pitch_insights.agents.desk import CommentaryDesk, Lines, agent_for, fallback_lines
from pitch_insights.agents.prompts import moment_input
from pitch_insights.agents.settings import AgentSettings, load_settings
from pitch_insights.agents.store import commentary_path, load_commentary, write_commentary
from pitch_insights.explain.moments import MatchBrain
from pitch_insights.generator.io import read_match

SAMPLE = Path(__file__).resolve().parents[2] / "samples" / "comeback-POT-CAR.jsonl"


@pytest.fixture(scope="module")
def match():
    meta, events = read_match(SAMPLE)
    brain = MatchBrain(meta)
    for ev in events:
        brain.update(ev)
    return meta, brain.moments


def winner(moments):
    """The 90+6' winner: Szobalenko, assisted by Musialetti, Carrot 3-2."""
    return [m for m in moments if m["type"] == "goal"][-1]


class FakeWriter:
    provider, model = "fake", "fake-model"

    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls: list[tuple[str, str]] = []

    async def write(self, role, prompt):
        self.calls.append((role, prompt))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        if reply == "slow":
            await asyncio.sleep(5)
        return reply


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------- grounding


def test_grounded_text_passes(match):
    meta, moments = match
    m = winner(moments)
    text = ("Szobalenko wins it for Carrot in the 96th minute, 3-2 at Potato FC. "
            "Their chance of winning jumped from 3% to 97% on an xG 0.08 finish, set up by Musialetti.")
    g = grounding.check(text, m, meta)
    assert g.passed, g.unsupported
    assert g.claims >= 8 and g.score == 1.0


def test_made_up_numbers_and_names_are_caught(match):
    meta, moments = match
    m = winner(moments)
    other_pot = next(p["name"] for p in meta["home"]["players"]
                     if p["name"].split()[-1] not in grounding.moment_text(m))
    g = grounding.check(f"Szobalenko's 4th goal in 12 games, past {other_pot}, sinks Broccoli.", m, meta)
    assert set(g.unsupported) >= {"4", "12", other_pot, "Broccoli FC"}
    assert 0 < g.score < 1


def test_text_without_claims_scores_one(match):
    meta, moments = match
    g = grounding.check("What a finish!", winner(moments), meta)
    assert g.passed and g.claims == 0 and g.score == 1.0


# ---------------------------------------------------------------- the desk


def test_routes_key_moments_to_the_explainer(match):
    _, moments = match
    roles = {m["type"]: agent_for(m) for m in moments}
    assert roles["goal"] == "explainer" and roles["full_time"] == "explainer"
    assert roles["momentum_swing"] == "narrator"


def test_only_shown_moments_get_commentary(match):
    meta, moments = match
    desk = CommentaryDesk(FakeWriter(), meta)
    assert all(desk.wants(m) == (m["tier"] != "minor") for m in moments)


def test_good_draft_is_kept(match):
    meta, moments = match
    good = Lines(casual="Szobalenko wins it for Carrot!", analyst="Carrot go from 3% to 97% to win.")
    writer = FakeWriter(good)
    rec = run(CommentaryDesk(writer, meta).comment(winner(moments)))
    assert rec["status"] == "ok" and rec["attempts"] == 1 and rec["casual"] == good.casual
    assert rec["grounding"]["score"] == 1.0 and rec["corrected"] == []
    assert len(writer.calls) == 1 and writer.calls[0][0] == "explainer"


def test_ungrounded_draft_is_retried_with_the_problems_named(match):
    meta, moments = match
    bad = Lines(casual="Szobalenko's 9th goal!", analyst="A 40-yard screamer.")
    good = Lines(casual="Szobalenko wins it late.", analyst="Carrot's win chance goes from 3% to 97%.")
    writer = FakeWriter(bad, good)
    rec = run(CommentaryDesk(writer, meta).comment(winner(moments)))
    assert rec["status"] == "ok" and rec["attempts"] == 2
    assert rec["corrected"] == ["9", "40"]
    assert "9, 40" in writer.calls[1][1]  # the retry names what was wrong


def test_two_bad_drafts_fall_back_to_the_headline(match):
    meta, moments = match
    m = winner(moments)
    bad = Lines(casual="A 9th goal.", analyst="9 of them.")
    rec = run(CommentaryDesk(FakeWriter(bad, bad), meta).comment(m))
    assert rec["status"] == "fallback" and rec["attempts"] == 2
    assert rec["casual"] == m["headline"] + "." and rec["reason"].startswith("not grounded")


@pytest.mark.parametrize("failure, reason", [
    (openai.RateLimitError("busy", response=httpx.Response(429, request=httpx.Request("POST", "http://x")), body=None),
     "service unavailable"),
    (openai.InternalServerError("down", response=httpx.Response(500, request=httpx.Request("POST", "http://x")),
                                body=None), "service unavailable"),
    (openai.BadRequestError("filtered", response=httpx.Response(400, request=httpx.Request("POST", "http://x")),
                            body=None), "request refused (400)"),
    (None, "no structured output"),
    ("slow", "timeout"),
])
def test_failures_fall_back_without_raising(match, failure, reason):
    meta, moments = match
    desk = CommentaryDesk(FakeWriter(failure), meta, timeout_s=0.05)
    rec = run(desk.comment(winner(moments)))
    assert rec["status"] == "fallback" and rec["reason"].startswith(reason)
    assert rec["casual"] and rec["analyst"]


def test_fallback_lines_use_the_headline_and_first_fact(match):
    _, moments = match
    m = winner(moments)
    lines = fallback_lines(m)
    assert lines.casual == m["headline"] + "." and m["facts"][0]["text"] in lines.analyst


def test_moment_input_shows_facts_not_raw_values(match):
    meta, moments = match
    text = moment_input(winner(moments), meta)
    assert "Facts:" in text and "Szobalenko" in text and "90+6'" in text
    assert "0.9669" not in text  # the writer sees the facts' wording, not internal values


# ---------------------------------------------------------------- settings and storage


def test_settings_read_env_and_reject_unknown_providers(monkeypatch, tmp_path):
    env = tmp_path / ".env"
    env.write_text("LLM_PROVIDER=foundry\nAZURE_OPENAI_ENDPOINT=https://r.services.ai.azure.com/openai/v1/responses\n"
                   "AZURE_OPENAI_API_KEY=k\nAZURE_OPENAI_DEPLOYMENT=gpt-4o\nAGENT_MAX_TOKENS=oops\n", encoding="utf-8")
    for k in ("LLM_PROVIDER", "AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_API_KEY", "AZURE_OPENAI_DEPLOYMENT"):
        monkeypatch.delenv(k, raising=False)
    s = load_settings(env)
    assert s.configured and s.model == "gpt-4o" and s.max_tokens == 220  # a bad number keeps the default
    assert "secret-key-123" not in repr(s)  # the key never shows in repr
    assert base_url(s) == "https://r.services.ai.azure.com/openai/v1/"
    monkeypatch.setenv("LLM_PROVIDER", "nope")
    with pytest.raises(ValueError, match="LLM_PROVIDER"):
        load_settings(env)


def test_unconfigured_provider_says_what_to_do():
    from pitch_insights.agents.clients import make_chat_client

    with pytest.raises(RuntimeError, match=".env"):
        make_chat_client(AgentSettings(provider="foundry"))


def test_commentary_file_round_trip(tmp_path):
    match_path = tmp_path / "m.jsonl"
    rec = {"moment_id": "M-1", "agent": "explainer", "status": "ok", "casual": "a", "analyst": "b",
           "attempts": 2, "grounding": {"score": 1.0, "claims": 3, "unsupported": []}, "corrected": ["9"],
           "reason": None}
    write_commentary(match_path, {"ai_generated": True, "model": "x", "prompt_version": "v"}, [rec])
    data = load_commentary(match_path)
    assert commentary_path(match_path).name == "m.commentary.json"
    assert data["moments"]["M-1"] == rec and data["summary"]["retried"] == 1 and data["ai_generated"]
    assert load_commentary(tmp_path / "missing.jsonl") == {"moments": {}}


def test_number_words_in_the_facts_back_digits(match):
    meta, moments = match
    m = next(x for x in moments if any("last five minutes" in f.get("text", "") for f in x["facts"]))
    assert grounding.check("Their best spell of the last 5 minutes.", m, meta).passed


def test_input_hash_changes_when_the_facts_do(match):
    from pitch_insights.agents.desk import input_hash

    meta, moments = match
    m = winner(moments)
    changed = m | {"facts": m["facts"][:-1]}
    assert input_hash(m, meta) == input_hash(dict(m), meta) != input_hash(changed, meta)
