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
import json
import logging
import time
from typing import Protocol

import openai
from opentelemetry import trace
from pydantic import BaseModel

from pitch_insights.agents import grounding
from pitch_insights.agents.middleware import RunLogMiddleware, moment_id_var
from pitch_insights.agents.prompts import (
    EXPLAINER_INSTRUCTIONS, NARRATOR_INSTRUCTIONS, PROMPT_VERSION, VIDEO_NARRATOR_INSTRUCTIONS, VIDEO_PROMPT_VERSION,
    input_hash, moment_input, retry_input,
)
from pitch_insights.agents.safety import ContentSafety

log = logging.getLogger("pitch_insights.agents")
tracer = trace.get_tracer("pitch_insights.agents")  # a no-op until tracing is set up (agents/tracing.py)

EXPLAINER_TYPES = {"goal", "red_card", "penalty_awarded", "big_chance_missed", "half_time", "full_time"}
COMMENTED_TIERS = {"headline", "notable"}
MAX_ATTEMPTS = 2  # the first draft plus one retry after a failed groundedness check


class Lines(BaseModel):
    """What a writing agent returns: the same point for two audiences."""
    casual: str
    analyst: str


class Writer(Protocol):
    """Anything that can write Lines for a role ("explainer", "narrator" or "video_narrator"). The Agent
    Framework implementation is AgentWriter; tests use a fake."""
    provider: str
    model: str

    async def write(self, role: str, prompt: str) -> Lines | None: ...


def agent_for(moment: dict) -> str:
    """Moments detected from video (`source == "video"`) go to the video narrator, whatever their type."""
    if moment.get("source") == "video":
        return "video_narrator"
    return "explainer" if moment["type"] in EXPLAINER_TYPES else "narrator"


class ProviderConfigError(RuntimeError):
    """The provider refused us outright (bad key, no access, wrong deployment): every moment would
    fail the same way, so stop rather than write a file of fallbacks."""


def _causes(exc: BaseException):
    """The exception and everything it wraps. Agent Framework re-raises OpenAI errors as its own
    ChatClientException, with the original as the cause."""
    seen = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        yield exc
        exc = getattr(exc, "inner_exception", None) or exc.__cause__


def failure_reason(exc: BaseException) -> str | None:
    """Why a draft failed, for the record; None if it isn't a provider failure (a bug, so re-raise).
    Raises ProviderConfigError for errors no retry or fallback can fix."""
    from agent_framework.exceptions import ChatClientContentFilterException, ChatClientException

    for e in _causes(exc):
        if isinstance(e, (openai.AuthenticationError, openai.PermissionDeniedError, openai.NotFoundError)):
            raise ProviderConfigError(f"the model provider refused the request ({e.status_code}); "
                                      "check the endpoint, key and deployment name in .env") from exc
        if isinstance(e, (openai.RateLimitError, openai.APITimeoutError, openai.APIConnectionError,
                          openai.InternalServerError)):
            return f"service unavailable ({type(e).__name__})"  # the SDK has already retried
        if isinstance(e, ChatClientContentFilterException):
            return "request refused (content filter)"
        if isinstance(e, openai.APIStatusError):
            return f"request refused ({e.status_code})"  # not worth retrying
    if isinstance(exc, ChatClientException):
        return f"service error ({type(exc).__name__})"
    return None


def fallback_lines(moment: dict) -> Lines:
    first = next((f["text"] for f in moment.get("facts", []) if f.get("text")), "")
    return Lines(casual=moment["headline"] + ".", analyst=f"{moment['headline']}. {first}".strip())


class CommentaryDesk:
    def __init__(self, writer: Writer, meta: dict, timeout_s: float = 45.0, safety: ContentSafety | None = None):
        self.writer = writer
        self.meta = meta
        self.timeout_s = timeout_s  # the whole draft, including the SDK's own retries
        self.safety = safety        # Azure AI Content Safety; None skips the check (tests, no .env values)

    def wants(self, moment: dict) -> bool:
        return moment["tier"] in COMMENTED_TIERS

    async def screen(self, record: dict, moment: dict) -> dict:
        """Run the safety check on a stored record that hasn't had one (no model call): a line written
        before the check existed, or a grounded draft kept as `pending` because the service couldn't be
        reached. A blocked line becomes the plain headline. If the service still can't answer, a record that
        already waits as `pending` is left as it is, and an older line that was never screened is taken out of
        view too: it becomes the plain headline with its text kept as `pending`, so nothing unchecked is shown
        and the next run screens it again."""
        if self.safety is None:
            return record
        pending = record.get("pending")
        if pending:
            casual, analyst = pending["casual"], pending["analyst"]
        elif record["status"] == "ok" and not record.get("safety"):
            casual, analyst = record["casual"], record["analyst"]
        else:
            return record
        res = await self.safety.check(f"{casual}\n{analyst}")
        if res.error:
            if pending:
                return record  # already the headline, with the draft kept
            lines = fallback_lines(moment)
            return record | {"status": "fallback", "casual": lines.casual, "analyst": lines.analyst,
                             "pending": {"casual": casual, "analyst": analyst}, "reason": res.reason}
        record = {k: v for k, v in record.items() if k != "pending"} | {"safety": res.to_dict()}
        if res.passed:
            return record | {"status": "ok", "casual": casual, "analyst": analyst, "reason": None}
        lines = fallback_lines(moment)
        return record | {"status": "fallback", "casual": lines.casual, "analyst": lines.analyst, "reason": res.reason}

    async def comment(self, moment: dict) -> dict:
        """Commentary for one moment. Always returns a record; status says how it was made."""
        with tracer.start_as_current_span("commentary", attributes={"pitch.moment_id": moment["id"]}) as span:
            record = await self._comment(moment)
            span.set_attributes({"pitch.agent": record["agent"], "pitch.status": record["status"],
                                 "pitch.attempts": record["attempts"], "pitch.reason": record["reason"] or "",
                                 "pitch.grounding_score": (record["grounding"] or {}).get("score", -1.0),
                                 "pitch.safety_passed": bool((record["safety"] or {}).get("passed"))})
            return record

    async def _comment(self, moment: dict) -> dict:
        token = moment_id_var.set(moment["id"])
        role = agent_for(moment)
        started = time.perf_counter()
        prompt = moment_input(moment, self.meta)
        attempts, lines, check, reason, safety = 0, None, None, "", None
        corrected: list[str] = []  # what the groundedness check caught in earlier drafts
        try:
            while attempts < MAX_ATTEMPTS:
                attempts += 1
                try:
                    lines = await asyncio.wait_for(self.writer.write(role, prompt), self.timeout_s)
                except TimeoutError:
                    reason = "timeout"
                    break
                except Exception as e:
                    reason = failure_reason(e)
                    if reason is None:
                        raise
                    break
                if lines is None:
                    reason = "no structured output"
                    break
                check = grounding.check(f"{lines.casual} {lines.analyst}", moment, self.meta)
                check = grounding.with_hedging(check, lines.casual, lines.analyst, moment)  # video moments only
                if check.passed:
                    reason = ""
                    break
                reason = "not grounded: " + ", ".join(check.unsupported)
                corrected += check.unsupported
                prompt = retry_input(moment, self.meta, check.unsupported)
            ok = lines is not None and check is not None and check.passed
            pending = None
            if ok and self.safety is not None:  # only grounded text is worth screening
                safety = await self.safety.check(f"{lines.casual}\n{lines.analyst}")
                if not safety.passed:
                    ok, reason = False, safety.reason
                    if safety.error:  # unchecked, not unsafe: keep the draft to screen again later
                        pending = {"casual": lines.casual, "analyst": lines.analyst}
            if not ok:
                lines = fallback_lines(moment)
            record = {
                "moment_id": moment["id"], "input_hash": input_hash(moment, self.meta), "agent": role,
                "status": "ok" if ok else "fallback",
                "casual": lines.casual, "analyst": lines.analyst, "attempts": attempts,
                "grounding": check.to_dict() if check else None, "corrected": corrected,
                "safety": safety.to_dict() if safety else None,
                "reason": reason or None, "provider": self.writer.provider, "model": self.writer.model,
            }
            if pending:
                record["pending"] = pending
            log.info(json.dumps({"event": "commentary", "moment_id": moment["id"], "agent": role,
                                 "status": record["status"], "attempts": attempts, "reason": reason or None,
                                 "grounding": record["grounding"],
                                 "safety_passed": safety.passed if safety else None,
                                 "ms": round((time.perf_counter() - started) * 1000)}))
            return record
        finally:
            moment_id_var.reset(token)


class AgentWriter:
    """The three writing agents, built with Microsoft Agent Framework."""

    def __init__(self, client, provider: str, model: str, max_tokens: int = 220, temperature: float = 0.4):
        from agent_framework import Agent

        self.provider, self.model, self.client = provider, model, client
        self.options = {"response_format": Lines, "max_tokens": max_tokens, "temperature": temperature}
        mw = [RunLogMiddleware()]
        self.agents = {
            "explainer": Agent(client, EXPLAINER_INSTRUCTIONS, name="explainer",
                               description="Explains why a key moment matters, from its evidence pack.",
                               middleware=mw),
            "narrator": Agent(client, NARRATOR_INSTRUCTIONS, name="narrator",
                              description="Describes the flow of play between key moments.", middleware=mw),
            "video_narrator": Agent(client, VIDEO_NARRATOR_INSTRUCTIONS, name="video_narrator",
                                    description="Describes a passage of play detected from real match footage.",
                                    middleware=mw),
        }

    async def aclose(self) -> None:
        """Close the HTTP connection pool behind the chat client."""
        oai = getattr(self.client, "client", None)
        if oai is not None:
            await oai.close()

    async def write(self, role: str, prompt: str) -> Lines | None:
        response = await self.agents[role].run(prompt, options=self.options)
        try:
            # .value parses the reply on first access and raises (ValidationError is a ValueError)
            # when it isn't JSON in the Lines shape; the desk treats None as "no structured output".
            value = response.value
            return value if isinstance(value, Lines) else Lines.model_validate_json(response.text)
        except ValueError:
            return None


def writer_from_settings(settings) -> AgentWriter:
    from pitch_insights.agents.clients import make_chat_client

    return AgentWriter(make_chat_client(settings), settings.provider, settings.model,
                       max_tokens=settings.max_tokens, temperature=settings.temperature)


def file_header(writer: Writer, video: bool = False) -> dict:
    """What a stored commentary file says about who wrote it. The video clip's file has its own prompt version."""
    return {"ai_generated": True, "provider": writer.provider, "model": writer.model,
            "prompt_version": VIDEO_PROMPT_VERSION if video else PROMPT_VERSION}
