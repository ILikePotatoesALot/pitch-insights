"""Precompute the Memory agent's embeddings for the sample matches.

    python scripts/embed_moments.py                     # every sample in ../samples
    python scripts/embed_moments.py comeback-POT-CAR    # one match
    python scripts/embed_moments.py --force             # re-embed everything

Runs each match through MatchBrain with the Memory agent, collects the description of every
moment it remembers, and embeds the ones not already stored (Foundry, text-embedding-3-small,
256 dimensions) in as few requests as the service allows. Writes samples/<name>.memory.json,
so replays and the stored commentary never call the network. Nothing to embed means no call.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from pitch_insights.agents.clients import make_embeddings_client
from pitch_insights.agents.memory import MemoryAgent, embed_batch, load_vectors, write_vectors
from pitch_insights.agents.settings import load_settings
from pitch_insights.explain.moments import MatchBrain
from pitch_insights.generator.io import read_match

SAMPLES = Path(__file__).resolve().parents[2] / "samples"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("names", nargs="*", help="sample names (default: all)")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    paths = [SAMPLES / f"{n}.jsonl" for n in args.names] if args.names else sorted(SAMPLES.glob("*.jsonl"))
    if missing := [p.name for p in paths if not p.exists()]:
        print("No such sample: " + ", ".join(missing))
        return 1
    settings, client = load_settings(), None
    try:
        for path in paths:
            meta, events = read_match(path)
            stored = load_vectors(path)
            if args.force:
                stored.vectors = {}
            brain = MatchBrain(meta, memory=MemoryAgent(meta, stored))
            for ev in events:
                brain.update(ev)
            texts = list(stored.asked)
            todo = [t for t in texts if t not in stored.vectors]
            model = stored.model
            if todo:
                client = client or make_embeddings_client(settings)
                model, vectors = embed_batch(client, settings.embedding_model, todo)
                stored.vectors.update(zip(todo, vectors))
            out = write_vectors(path, model, {t: stored.vectors[t] for t in texts})
            print(f"{path.stem}: {len(texts)} moments remembered, {len(todo)} embedded  ->  {out.name}")
    finally:
        if client is not None:
            client.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
