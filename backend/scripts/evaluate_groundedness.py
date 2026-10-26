"""Second opinion on the stored commentary: Foundry's groundedness evaluator.

    python scripts/evaluate_groundedness.py                     # every sample in ../samples
    python scripts/evaluate_groundedness.py comeback-POT-CAR    # one match
    python scripts/evaluate_groundedness.py 117093-38min_ft     # the real-footage clip, in samples/video/

Our own groundedness check (agents/grounding.py) only sees names and numbers. This asks a
judge model (the Foundry GPT-4o deployment, through azure-ai-evaluation's GroundednessEvaluator)
whether each line is supported by the facts the writer was shown, scoring 1 to 5 (3 or more
passes). It catches claims our check can't, such as "dominating" without the numbers to back it:
https://learn.microsoft.com/en-us/azure/ai-foundry/concepts/evaluation-evaluators/rag-evaluators

Only lines not yet scored for the same text are sent, so re-running is cheap. Writes
samples/<name>.evaluation.json (samples/video/<name>.evaluation.json for the clip). Run it after
scripts/generate_commentary.py. With no names, every sample match and clip is done.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
import warnings
from pathlib import Path
from urllib.parse import urlsplit

import truststore

from pitch_insights.agents.memory import memory_for
from pitch_insights.agents.prompts import moment_input
from pitch_insights.agents.settings import load_settings
from pitch_insights.agents.store import load_commentary, sibling_path, with_commentary, write_json
from pitch_insights.explain.moments import MatchBrain
from pitch_insights.generator.io import read_match
from pitch_insights.video.moments import load_clip_moments
from pitch_insights.video.replay import APP_CLIPS, CLIP_DIR, stored_path

SAMPLES = Path(__file__).resolve().parents[2] / "samples"
API_VERSION = "2024-10-21"  # the evaluator's Azure OpenAI client needs a dated API version
QUERY = "Describe this football moment and why it matters, using only the facts given."


def text_hash(context: str, response: str) -> str:
    return hashlib.sha256(f"{context}\x1f{response}".encode()).hexdigest()[:16]


def is_clip(path: Path) -> bool:
    """A clip's stored files are named as if for `samples/video/<name>.jsonl` (see video.replay.stored_path)."""
    return path.parent.name == CLIP_DIR


def sample_paths(names: list[str]) -> list[Path]:
    if not names:
        return sorted(SAMPLES.glob("*.jsonl")) + [stored_path(SAMPLES, n) for n in APP_CLIPS]
    return [stored_path(SAMPLES, n) if (SAMPLES / CLIP_DIR / f"{n}.frames.jsonl").exists() else SAMPLES / f"{n}.jsonl"
            for n in names]


def run_match(path: Path, evaluator, model: str) -> dict:
    if is_clip(path):
        meta, all_moments = load_clip_moments(SAMPLES, path.stem)
    else:
        meta, events = read_match(path)
        brain = MatchBrain(meta, memory=memory_for(path, meta))
        for ev in events:
            brain.update(ev)
        all_moments = brain.moments
    stored = load_commentary(path)
    out_path = sibling_path(path, ".evaluation.json")
    try:
        old = json.loads(out_path.read_text(encoding="utf-8")).get("moments", {})
    except (OSError, ValueError):
        old = {}

    results = {}
    for m in all_moments:
        c = with_commentary(m, stored, meta).get("commentary")
        if not c or c["status"] != "ok":
            continue
        context = moment_input(m, meta)
        response = f"{c['casual']} {c['analyst']}"
        h = text_hash(context, response)
        if old.get(m["id"], {}).get("text_hash") == h:
            results[m["id"]] = old[m["id"]]
            continue
        try:
            r = evaluator(query=QUERY, context=context, response=response)
        except Exception as e:  # a rate limit or timeout: record it unscored, so the next run tries again
            results[m["id"]] = {"text_hash": None, "score": None, "result": None, "error": type(e).__name__}
            continue
        results[m["id"]] = {"text_hash": h, "score": r.get("groundedness"), "result": r.get("groundedness_result"),
                            "reason": r.get("groundedness_reason")}
    scores = [r["score"] for r in results.values() if isinstance(r.get("score"), (int, float))]
    summary = {"moments": len(results), "mean": round(statistics.fmean(scores), 2) if scores else None,
               "min": min(scores) if scores else None,
               "passed": sum(r.get("result") == "pass" for r in results.values()),
               "not_scored": sum(bool(r.get("error")) for r in results.values())}
    write_json(out_path, {"evaluator": "azure-ai-evaluation GroundednessEvaluator", "judge_model": model,
                          "scale": "1-5, pass at 3", "summary": summary, "moments": results})
    low = {k: v for k, v in results.items() if isinstance(v.get("score"), (int, float)) and v["score"] < 4}
    print(f"{path.stem}: {summary}  ->  {out_path.name}")
    for k, v in low.items():
        print(f"  {k} scored {v['score']}: {(v.get('reason') or '')[:200]}")
    return summary


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("names", nargs="*", help="sample names (default: all)")
    args = ap.parse_args()
    settings = load_settings()
    if not (settings.embedding_endpoint and settings.embedding_api_key and settings.model):
        print("Foundry isn't configured in .env (see .env.example)")
        return 1
    truststore.inject_into_ssl()  # the evaluator's HTTP client uses Python's bundled certificates otherwise
    warnings.filterwarnings("ignore")
    from azure.ai.evaluation import AzureOpenAIModelConfiguration, GroundednessEvaluator

    url = urlsplit(settings.embedding_endpoint)  # always the Foundry resource, whatever the chat provider;
    endpoint = f"{url.scheme}://{url.netloc}/"   # the host only, as the Azure OpenAI client expects
    model = settings.model if settings.provider == "foundry" else "gpt-4o"
    config = AzureOpenAIModelConfiguration(azure_endpoint=endpoint, api_key=settings.embedding_api_key,
                                           azure_deployment=model, api_version=API_VERSION)
    evaluator = GroundednessEvaluator(config)
    paths = sample_paths(args.names)
    for path in paths:
        run_match(path, evaluator, model)
    return 0


if __name__ == "__main__":
    sys.exit(main())
