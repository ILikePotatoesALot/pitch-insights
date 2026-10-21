"""The Memory agent, with fake embedders: no key, no network."""

import json
import re
import zlib
from pathlib import Path
from types import SimpleNamespace

import httpx
import openai
import pytest

from pitch_insights.agents import grounding, memory
from pitch_insights.agents.memory import (
    DIMENSIONS, FoundryEmbedder, MemoryAgent, StoredVectors, embed_batch, load_vectors, normalise, write_vectors,
)
from pitch_insights.explain.moments import MatchBrain
from pitch_insights.generator.engine import simulate
from pitch_insights.generator.io import read_match

SAMPLES = Path(__file__).resolve().parents[2] / "samples"


class Words:
    """A fake embedder: a bag of words hashed into the vector, so shared words mean similar."""

    def __init__(self):
        self.asked = []

    def vector(self, text):
        self.asked.append(text)
        v = [0.0] * DIMENSIONS
        for w in re.findall(r"[a-z']+", text.lower()):
            v[zlib.crc32(w.encode()) % DIMENSIONS] += 1
        return normalise(v)


class Same:
    """Every text gets the same vector, so only the code filter decides."""

    def vector(self, text):
        return normalise([1.0] * DIMENSIONS)


def axis(*weights):
    """A unit vector from its first few components."""
    return normalise(list(weights) + [0.0] * (DIMENSIONS - len(weights)))


class ByPlayer:
    """Vectors chosen per player, to set exact similarities."""

    def __init__(self, vectors):
        self.vectors = vectors

    def vector(self, text):
        return next((v for name, v in self.vectors.items() if name in text), None)


def run(meta, events, embedder):
    agent = MemoryAgent(meta, embedder)
    brain = MatchBrain(meta, memory=agent)
    for e in events:
        brain.update(e)
    return brain, agent


@pytest.fixture(scope="module")
def match():
    return simulate(7, "POT", "CAR")


def memory_facts(m):
    return [f for f in m["facts"] if f["kind"] == "memory"]


def test_only_compares_moments_of_the_same_family_and_team(match):
    meta, events, _ = match
    brain, agent = run(meta, events, Same())
    by_id = {m["id"]: m for m in brain.moments}
    linked = 0
    for m in brain.moments:
        for f in memory_facts(m):
            if "moment_id" not in f["value"]:
                continue
            linked += 1
            earlier = by_id[f["value"]["moment_id"]]
            assert memory.FAMILIES[earlier["type"]] == memory.FAMILIES[m["type"]]
            assert earlier["team_id"] == m["team_id"] or m["type"] == "red_card"
    assert linked  # with identical vectors, every moment with an earlier peer links to it


def test_only_headline_and_notable_moments_get_memory(match):
    meta, events, _ = match
    brain, _ = run(meta, events, Same())
    assert all(not memory_facts(m) for m in brain.moments if m["tier"] == "minor")
    assert all(not memory_facts(m) for m in brain.moments if m["type"] not in memory.FAMILIES)


def test_never_looks_ahead(match):
    meta, events, _ = match
    full, _ = run(meta, events, Words())
    k = len(events) // 2
    partial, _ = run(meta, events[:k], Words())
    assert partial.moments == full.moments[:len(partial.moments)]
    order = {m["id"]: i for i, m in enumerate(full.moments)}
    for m in full.moments:
        for f in memory_facts(m):
            if "moment_id" in f["value"]:
                assert order[f["value"]["moment_id"]] < order[m["id"]]


def chance(mid, player, minute, tier="headline", team="POT"):
    return {"id": mid, "seq": minute * 10, "clock": f"{minute}'", "type": "goal", "team_id": team,
            "player_id": player, "tier": tier, "facts": [{"kind": "chance", "value": 0.31, "text": "A big chance."}]}


def test_ranks_by_similarity_keeps_the_top_two_above_the_threshold():
    meta = json.loads((SAMPLES / "comeback-POT-CAR.jsonl").open(encoding="utf-8").readline())
    pid = {p["name"].split()[-1]: p["id"] for p in meta["home"]["players"]}
    a, b, c, d = list(pid)[:4]
    vectors = {a: axis(1, 0.48), b: axis(1, 0.2), c: axis(1, 0.75), d: axis(0, 1)}
    agent = MemoryAgent(meta, ByPlayer(vectors), threshold=0.82)
    moments = [chance("M-1", pid[a], 10), chance("M-2", pid[b], 20), chance("M-3", pid[d], 30),
               chance("M-4", pid[c], 40)]
    for m in moments:
        agent.update({"type": "pressure"}, [m])
    query = moments[3]
    links = [f["value"]["moment_id"] for f in memory_facts(query) if "moment_id" in f["value"]]
    assert links == ["M-1", "M-2"]  # most similar first; M-3 is below the threshold
    sims = [f["similarity"] for f in memory_facts(query) if "similarity" in f]
    assert sims == sorted(sims, reverse=True) and min(sims) >= 0.82
    count = memory_facts(query)[-1]
    assert count["value"]["count"] == 4 and "That makes 4 Potato goals or big chances" in count["text"]


def test_adds_nothing_when_nothing_is_similar_enough():
    meta = json.loads((SAMPLES / "comeback-POT-CAR.jsonl").open(encoding="utf-8").readline())
    pid = [p["id"] for p in meta["home"]["players"]]
    names = [p["name"].split()[-1] for p in meta["home"]["players"]]
    agent = MemoryAgent(meta, ByPlayer({names[0]: axis(1, 0), names[1]: axis(0, 1)}))
    first, second = chance("M-1", pid[0], 10), chance("M-2", pid[1], 20)
    agent.update({"type": "pressure"}, [first])
    agent.update({"type": "pressure"}, [second])
    assert not memory_facts(first) and not memory_facts(second)


def test_missing_vectors_mean_no_memory(match):
    meta, events, _ = match
    brain, agent = run(meta, events, StoredVectors())
    assert not any(memory_facts(m) for m in brain.moments)
    assert agent.embedder.asked  # but it recorded what to embed


def test_memory_facts_pass_the_groundedness_check():
    path = SAMPLES / "comeback-POT-CAR.jsonl"
    meta, events = read_match(path)
    brain, _ = run(meta, events, memory.load_vectors(path))
    m = next(m for m in brain.moments if any("moment_id" in f["value"] for f in memory_facts(m)) and m["type"] == "goal")
    earlier = next(f for f in memory_facts(m) if "moment_id" in f["value"])
    who = earlier["text"].split(": ", 1)[1].split()[0].removesuffix("'s")
    text = f"{who} again, after the chance at {earlier['value']['clock']}, {memory_facts(m)[-1]['value']['count']} in all."
    assert grounding.check(text, m, meta).passed


def test_stored_vectors_round_trip(tmp_path):
    match_path = tmp_path / "x.jsonl"
    v = Words().vector("Potato FC goal: Madekuta scored.")
    write_vectors(match_path, "text-embedding-3-small", {"Potato FC goal: Madekuta scored.": v})
    stored = load_vectors(match_path)
    assert stored.model == "text-embedding-3-small"
    back = stored.vector("Potato FC goal: Madekuta scored.")
    assert len(back) == DIMENSIONS and max(abs(x - y) for x, y in zip(v, back)) < 1e-6
    assert stored.vector("something else") is None


@pytest.mark.parametrize("content", ["not json", '{"dimensions": 1536, "vectors": {}}', '{"vectors": {}}',
                                     json.dumps({"dimensions": DIMENSIONS, "vectors": {"t": memory.pack([1.0, 0.0])}})])
def test_bad_stored_files_mean_no_vectors(tmp_path, content):
    match_path = tmp_path / "x.jsonl"
    memory.memory_path(match_path).write_text(content, encoding="utf-8")
    assert load_vectors(match_path).vectors == {}
    assert load_vectors(tmp_path / "missing.jsonl").vectors == {}


class FakeEmbeddings:
    def __init__(self, fail=None, dims=DIMENSIONS):
        self.calls, self.fail, self.dims = [], fail, dims

    def create(self, model, input, dimensions):
        self.calls.append(len(input))
        if self.fail:
            raise self.fail
        data = [SimpleNamespace(index=i, embedding=[1.0] + [0.0] * (self.dims - 1)) for i in reversed(range(len(input)))]
        return SimpleNamespace(data=data, model="text-embedding-3-small")


def test_embed_batch_splits_large_requests(monkeypatch):
    monkeypatch.setattr(memory, "BATCH", 3)
    client = SimpleNamespace(embeddings=FakeEmbeddings())
    model, vectors = embed_batch(client, "my-deployment", [f"t{i}" for i in range(7)])
    assert client.embeddings.calls == [3, 3, 1] and len(vectors) == 7 and model == "text-embedding-3-small"


@pytest.mark.parametrize("fail", [
    openai.APIConnectionError(request=httpx.Request("POST", "https://example.invalid")),
    openai.APITimeoutError(request=httpx.Request("POST", "https://example.invalid")),
    openai.RateLimitError("slow down", response=httpx.Response(429, request=httpx.Request("POST", "https://x")), body=None),
])
def test_live_embedder_falls_back_to_no_memory(fail):
    client = SimpleNamespace(embeddings=FakeEmbeddings(fail=fail))
    emb = FoundryEmbedder(client, "my-deployment")
    assert emb.vector("Potato FC goal") is None
    assert emb.vector("Carrot FC goal") is None and client.embeddings.calls == [1]  # paused after a failure


def test_live_embedder_rejects_a_malformed_response_and_caches_good_ones():
    bad = FoundryEmbedder(SimpleNamespace(embeddings=FakeEmbeddings(dims=8)), "d")
    assert bad.vector("Potato FC goal") is None
    good = FoundryEmbedder(SimpleNamespace(embeddings=FakeEmbeddings()), "d")
    assert good.vector("Potato FC goal") == good.vector("Potato FC goal")
    assert good.client.embeddings.calls == [1]


def test_live_embedder_in_a_match_without_a_service(match):
    meta, events, _ = match
    fail = openai.APIConnectionError(request=httpx.Request("POST", "https://example.invalid"))
    brain, _ = run(meta, events, FoundryEmbedder(SimpleNamespace(embeddings=FakeEmbeddings(fail=fail)), "d"))
    plain = MatchBrain(meta)
    for e in events:
        plain.update(e)
    assert brain.moments == plain.moments  # the match goes on, just without memory facts
