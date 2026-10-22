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


def status_error(cls, code):
    return cls("refused", response=httpx.Response(code, request=httpx.Request("POST", "https://x")), body=None)


def test_live_embedder_stops_for_the_match_on_a_config_error():
    client = SimpleNamespace(embeddings=FakeEmbeddings(fail=status_error(openai.AuthenticationError, 401)))
    emb = FoundryEmbedder(client, "my-deployment")
    assert emb.vector("Potato FC goal") is None
    emb._paused_until -= 10_000  # long after any transient pause would have ended
    assert emb.vector("Carrot FC goal") is None and client.embeddings.calls == [1]


def test_live_embedder_skips_only_the_text_a_400_refuses():
    client = SimpleNamespace(embeddings=FakeEmbeddings(fail=status_error(openai.BadRequestError, 400)))
    emb = FoundryEmbedder(client, "my-deployment")
    assert emb.vector("Potato FC goal") is None
    assert emb.vector("Carrot FC goal") is None and client.embeddings.calls == [1, 1]  # no pause


def on_ball(seq, t, etype, player, x, y, team="POT", **extra):
    return {"seq": seq, "t": t, "period": 1, "type": etype, "team_id": team, "player_id": player,
            "possession_id": None, "x": x, "y": y} | extra


def test_build_up_without_possession_ids():
    """Video events have no possession ids: winning the ball must still start a new possession,
    and the flank comes from the shooter's last run, not the first."""
    meta = json.loads((SAMPLES / "comeback-POT-CAR.jsonl").open(encoding="utf-8").readline())
    home = [p["id"] for p in meta["home"]["players"]]
    agent = MemoryAgent(meta, StoredVectors())
    events = [
        on_ball(1, 0.0, "pass", home[5], 30, 34, kind="open_play", receiver_id=home[9], outcome="complete"),
        {"seq": 2, "t": 5.0, "period": 1, "type": "interception", "team_id": "CAR", "player_id": "CAR-04",
         "possession_id": None, "x": 70, "y": 30, "outcome": "won"},
        {"seq": 3, "t": 40.0, "period": 1, "type": "recovery", "team_id": "POT", "player_id": home[9],
         "possession_id": None, "x": 40, "y": 10, "outcome": "won"},
        on_ball(4, 41.0, "carry", home[9], 40, 10, end_x=60, end_y=12),
        on_ball(5, 44.0, "carry", home[9], 70, 34, end_x=90, end_y=34),
        on_ball(6, 47.0, "shot", home[9], 95, 34, kind="open_play", outcome="goal", body_part="right_foot", xg=0.4),
    ]
    for ev in events[:-1]:
        agent.update(ev, [])
    goal = chance("M-1", home[9], 1) | {"seq": 6}
    agent.update(events[-1], [goal])
    text = agent.records[0]["text"]
    assert "down the middle, on the break" in text, text


def test_every_sample_has_vectors_for_every_moment_it_remembers():
    """The replay hides stored commentary whose memory facts are missing, so the stored vectors
    must cover every description the agent asks for."""
    for path in sorted(SAMPLES.glob("*.jsonl")):
        meta, events = read_match(path)
        stored = load_vectors(path)
        brain, _ = run(meta, events, stored)
        assert stored.vectors and set(stored.asked) <= set(stored.vectors), path.name


def test_memory_for_warns_when_vectors_are_missing(tmp_path, caplog):
    meta = json.loads((SAMPLES / "comeback-POT-CAR.jsonl").open(encoding="utf-8").readline())
    with caplog.at_level("WARNING", logger="pitch_insights.agents"):
        agent = memory.memory_for(tmp_path / "missing.jsonl", meta)
    assert agent.embedder.vectors == {} and "memory_vectors_missing" in caplog.text
    path = SAMPLES / "comeback-POT-CAR.jsonl"
    assert memory.memory_for(path, meta).embedder is memory.memory_for(path, meta).embedder  # loaded once


# ------------------------------------------------- the stored-vector cache (scripts/embed_moments.py)


def _stored(tmp_path, deployment, model="text-embedding-3-small", texts=("a", "b")):
    path = tmp_path / "x.jsonl"
    v = [1.0] + [0.0] * (DIMENSIONS - 1)
    write_vectors(path, model, {t: v for t in texts}, deployment)
    return load_vectors(path)


SAME_VECTOR = [1.0] + [0.0] * (DIMENSIONS - 1)  # what _stored writes: a deployment of the same model repeats it
OTHER_VECTOR = [0.0, 1.0] + [0.0] * (DIMENSIONS - 2)


def _fake_embed(model="text-embedding-3-small", vector=OTHER_VECTOR):
    calls = []

    def embed(texts):
        calls.append(list(texts))
        return model, [list(vector) for _ in texts]

    return embed, calls


def test_the_deployment_is_stored_with_the_vectors(tmp_path):
    assert _stored(tmp_path, "emb-small").deployment == "emb-small"
    assert json.loads(memory.memory_path(tmp_path / "x.jsonl").read_text(encoding="utf-8"))["deployment"] == "emb-small"


def test_an_unchanged_deployment_with_a_complete_cache_embeds_nothing(tmp_path):
    stored = _stored(tmp_path, "emb-small")
    embed, calls = _fake_embed()
    model, n, changed = memory.refresh_vectors(stored, ["a", "b"], "emb-small", embed)
    assert calls == [] and n == 0 and model == "text-embedding-3-small" and not changed


def test_a_changed_deployment_with_a_complete_cache_embeds_everything_again(tmp_path):
    """The cache is complete, so nothing needs embedding, but the vectors come from another model
    and can't be compared with the ones the new deployment makes."""
    stored = _stored(tmp_path, "emb-small")
    embed, calls = _fake_embed(model="text-embedding-3-large")
    model, n, changed = memory.refresh_vectors(stored, ["a", "b"], "emb-large", embed)
    assert calls == [["a", "b"]] and n == 2 and model == "text-embedding-3-large" and changed
    assert stored.deployment == "emb-large" and stored.vector("a")[1] == 1.0  # the new vectors, not the old


def test_a_legacy_file_is_adopted_only_after_a_probe_matches(tmp_path):
    """A file from before the deployment was stored can't say where its vectors came from, so one text is
    embedded with the configured deployment and compared: the same model gives the same vector."""
    stored = _stored(tmp_path, "")
    embed, calls = _fake_embed(vector=SAME_VECTOR)
    _, n, changed = memory.refresh_vectors(stored, ["a", "b"], "emb-small", embed)
    assert calls == [["a"]] and n == 0 and not changed  # one probe, nothing re-embedded
    assert stored.deployment == "emb-small" and stored.vector("b") == pytest.approx(SAME_VECTOR)


def test_a_probe_that_cannot_run_leaves_a_legacy_file_unadopted(tmp_path):
    stored = _stored(tmp_path, "")

    def down(texts):
        raise ConnectionError("service unreachable")

    with pytest.raises(ConnectionError):
        memory.refresh_vectors(stored, ["a", "b"], "emb-large", down)
    assert stored.deployment == "" and set(stored.vectors) == {"a", "b"}  # not stamped, not emptied


def test_a_legacy_file_from_another_model_is_not_relabelled(tmp_path):
    """The reported model differs: these small-model vectors must not be stamped with the large deployment."""
    stored = _stored(tmp_path, "", model="text-embedding-3-small")
    embed, calls = _fake_embed(model="text-embedding-3-large", vector=SAME_VECTOR)
    model, n, changed = memory.refresh_vectors(stored, ["a", "b"], "emb-large", embed)
    assert calls == [["a"], ["a", "b"]] and n == 2 and changed and model == "text-embedding-3-large"
    assert stored.model == "text-embedding-3-large" and stored.deployment == "emb-large"


def test_a_legacy_file_whose_vectors_differ_is_embedded_again(tmp_path):
    """The same model name, but the vector for the probe text isn't the stored one."""
    stored = _stored(tmp_path, "")
    embed, calls = _fake_embed(vector=OTHER_VECTOR)
    _, n, changed = memory.refresh_vectors(stored, ["a", "b"], "emb-small", embed)
    assert calls == [["a"], ["a", "b"]] and n == 2 and changed
    assert stored.vector("a") == pytest.approx(OTHER_VECTOR)


def test_a_legacy_file_with_nothing_in_common_needs_no_probe(tmp_path):
    stored = _stored(tmp_path, "", texts=("x",))  # none of these texts is asked for
    embed, calls = _fake_embed()
    _, n, changed = memory.refresh_vectors(stored, ["a", "b"], "emb-small", embed)
    assert calls == [["a", "b"]] and n == 2 and not changed
    assert _stored(tmp_path, "", texts=()).vectors == {}  # and an empty cache has nothing to check
    embed, calls = _fake_embed()
    memory.refresh_vectors(load_vectors(tmp_path / "none.jsonl"), ["a"], "emb-small", embed)
    assert calls == [["a"]]


def test_force_and_new_texts_still_work(tmp_path):
    embed, calls = _fake_embed()
    memory.refresh_vectors(_stored(tmp_path, "emb-small"), ["a", "b"], "emb-small", embed, force=True)
    assert calls == [["a", "b"]]
    embed, calls = _fake_embed()
    stored = _stored(tmp_path, "emb-small")
    memory.refresh_vectors(stored, ["a", "b", "c"], "emb-small", embed)
    assert calls == [["c"]] and set(stored.vectors) == {"a", "b", "c"}


def test_a_model_that_changed_under_the_same_deployment_redoes_the_lot(tmp_path):
    stored = _stored(tmp_path, "emb-small")
    embed, calls = _fake_embed(model="text-embedding-3-large")  # the deployment was re-pointed
    _, n, changed = memory.refresh_vectors(stored, ["a", "b", "c"], "emb-small", embed)
    assert calls == [["c"], ["a", "b", "c"]] and n == 3


def test_the_embed_script_probes_a_legacy_cache_and_redoes_it_when_the_deployment_changes(tmp_path, monkeypatch, capsys):
    import importlib.util
    import shutil
    import sys

    spec = importlib.util.spec_from_file_location(
        "embed_moments", Path(__file__).resolve().parents[1] / "scripts" / "embed_moments.py")
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    shutil.copy(SAMPLES / "comeback-POT-CAR.jsonl", tmp_path / "m.jsonl")
    # A complete cache from before the deployment was stored (the committed sample may be stamped by now).
    legacy = json.loads((SAMPLES / "comeback-POT-CAR.memory.json").read_text(encoding="utf-8"))
    legacy.pop("deployment", None)
    legacy["model"] = "text-embedding-3-small"  # what the fake service reports
    legacy["vectors"] = {text: memory.pack(SAME_VECTOR) for text in legacy["vectors"]}  # what it returns
    (tmp_path / "m.memory.json").write_text(json.dumps(legacy), encoding="utf-8")
    monkeypatch.setattr(script, "SAMPLES", tmp_path)
    monkeypatch.setattr(sys, "argv", ["embed_moments.py"])
    embeddings = FakeEmbeddings()
    closed = []

    def run_script(deployment, client_allowed):
        monkeypatch.setattr(script, "load_settings", lambda: SimpleNamespace(embedding_model=deployment))

        def make_client(settings):
            assert client_allowed, "nothing needed embedding, so no client should be made"
            return SimpleNamespace(embeddings=embeddings, close=lambda: closed.append(1))

        monkeypatch.setattr(script, "make_embeddings_client", make_client)
        assert script.main() == 0
        return capsys.readouterr().out

    out = run_script("emb-small", client_allowed=True)  # an old file: one probe, then stamped
    assert "0 embedded" in out and embeddings.calls == [1] and closed == [1]
    assert load_vectors(tmp_path / "m.jsonl").deployment == "emb-small"
    out = run_script("emb-small", client_allowed=False)  # same deployment again: no call at all
    assert "0 embedded" in out and embeddings.calls == [1]
    total = len(load_vectors(tmp_path / "m.jsonl").vectors)
    out = run_script("emb-large", client_allowed=True)  # a different deployment: everything again
    assert "embedded everything again" in out and f"{total} embedded" in out
    assert sum(embeddings.calls) == 1 + total and closed == [1, 1]
    assert load_vectors(tmp_path / "m.jsonl").deployment == "emb-large"
