"""The commentary desk: routes each moment to a writing agent, checks the result, and
never lets a failure block the match.

Orchestration is deterministic code (Microsoft's guidance for predictable workflows):

    moment -> Explainer (key moments) or Narrator (flow of play)
           -> groundedness check -> one retry naming the unsupported claims
           -> fallback to the Moment Scorer's plain headline

Timeouts, rate limits and service errors also fall back, so a moment always has text.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from typing import Protocol

import openai
from pydantic import BaseModel

from pitch_insights.agents import grounding
from pitch_insights.agents.middleware import RunLogMiddleware, moment_id_var
from pitch_insights.agents.prompts import (
    EXPLAINER_INSTRUCTIONS, NARRATOR_INSTRUCTIONS, PROMPT_VERSION, moment_input, retry_input,
)

log = logging.getLogger("pitch_insights.agents")

EXPLAINER_TYPES = {"goal", "red_card", "penalty_awarded", "big_chance_missed", "half_time", "full_time"}
COMMENTED_TIERS = {"headline", "notable"}
MAX_ATTEMPTS = 2  # the first draft plus one retry after a failed groundedness check


class Lines(BaseModel):
    """What a writing agent returns: the same point for two audiences."""
    casual: str
    analyst: str


class Writer(Protocol):
    """Anything that can write Lines for a role ("explainer" or "narrator"). The Agent
    Framework implementation is AgentWriter; tests use a fake."""
    provider: str
    model: str

    async def write(self, role: str, prompt: str) -> Lines | None: ...


def agent_for(moment: dict) -> str:
    return "explainer" if moment["type"] in EXPLAINER_TYPES else "narrator"


def input_hash(moment: dict, meta: dict) -> str:
    """Fingerprint of what the writer is shown, so stored commentary is redone when the facts change."""
    return hashlib.sha256(moment_input(moment, meta).encode()).hexdigest()[:16]


def fallback_lines(moment: dict) -> Lines:
    first = next((f["text"] for f in moment.get("facts", []) if f.get("text")), "")
    return Lines(casual=moment["headline"] + ".", analyst=f"{moment['headline']}. {first}".strip())


class CommentaryDesk:
    def __init__(self, writer: Writer, meta: dict, timeout_s: float = 45.0):
        self.writer = writer
        self.meta = meta
        self.timeout_s = timeout_s  # the whole draft, including the SDK's own retries

    def wants(self, moment: dict) -> bool:
        return moment["tier"] in COMMENTED_TIERS

    async def comment(self, moment: dict) -> dict:
        """Commentary for one moment. Always returns a record; status says how it was made."""
        token = moment_id_var.set(moment["id"])
        role = agent_for(moment)
        started = time.perf_counter()
        prompt = moment_input(moment, self.meta)
        attempts, lines, check, reason = 0, None, None, ""
        corrected: list[str] = []  # what the groundedness check caught in earlier drafts
        try:
            while attempts < MAX_ATTEMPTS:
                attempts += 1
                try:
                    lines = await asyncio.wait_for(self.writer.write(role, prompt), self.timeout_s)
                except TimeoutError:
                    reason = "timeout"
                    break
                except (openai.RateLimitError, openai.APITimeoutError, openai.APIConnectionError,
                        openai.InternalServerError) as e:
                    reason = f"service unavailable ({type(e).__name__})"  # the SDK has already retried
                    break
                except openai.APIStatusError as e:
                    reason = f"request refused ({e.status_code})"  # e.g. a content filter; not worth retrying
                    break
                if lines is None:
                    reason = "no structured output"
                    break
                check = grounding.check(f"{lines.casual} {lines.analyst}", moment, self.meta)
                if check.passed:
                    reason = ""
                    break
                reason = "not grounded: " + ", ".join(check.unsupported)
                corrected += check.unsupported
                prompt = retry_input(moment, self.meta, check.unsupported)
            ok = lines is not None and check is not None and check.passed
            if not ok:
                lines = fallback_lines(moment)
            record = {
                "moment_id": moment["id"], "input_hash": input_hash(moment, self.meta), "agent": role,
                "status": "ok" if ok else "fallback",
                "casual": lines.casual, "analyst": lines.analyst, "attempts": attempts,
                "grounding": check.to_dict() if check else None, "corrected": corrected,
                "reason": reason or None,
            }
            log.info(json.dumps({"event": "commentary", "moment_id": moment["id"], "agent": role,
                                 "status": record["status"], "attempts": attempts, "reason": reason or None,
                                 "grounding": record["grounding"],
                                 "ms": round((time.perf_counter() - started) * 1000)}))
            return record
        finally:
            moment_id_var.reset(token)


class AgentWriter:
    """The two writing agents, built with Microsoft Agent Framework."""

    def __init__(self, client, provider: str, model: str, max_tokens: int = 220, temperature: float = 0.4):
        from agent_framework import Agent

        self.provider, self.model = provider, model
        self.options = {"response_format": Lines, "max_tokens": max_tokens, "temperature": temperature}
        mw = [RunLogMiddleware()]
        self.agents = {
            "explainer": Agent(client, EXPLAINER_INSTRUCTIONS, name="explainer",
                               description="Explains why a key moment matters, from its evidence pack.",
                               middleware=mw),
            "narrator": Agent(client, NARRATOR_INSTRUCTIONS, name="narrator",
                              description="Describes the flow of play between key moments.", middleware=mw),
        }

    async def write(self, role: str, prompt: str) -> Lines | None:
        response = await self.agents[role].run(prompt, options=self.options)
        value = response.value
        if isinstance(value, Lines):
            return value
        try:  # some providers return the JSON as text instead of a parsed value
            return Lines.model_validate_json(response.text)
        except ValueError:
            return None


def writer_from_settings(settings) -> AgentWriter:
    from pitch_insights.agents.clients import make_chat_client

    return AgentWriter(make_chat_client(settings), settings.provider, settings.model,
                       max_tokens=settings.max_tokens, temperature=settings.temperature)


def file_header(writer: Writer) -> dict:
    return {"ai_generated": True, "provider": writer.provider, "model": writer.model,
            "prompt_version": PROMPT_VERSION}
