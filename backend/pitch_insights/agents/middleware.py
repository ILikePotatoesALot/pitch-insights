"""Agent Framework middleware for cross-cutting concerns."""

from __future__ import annotations

import contextvars
import json
import logging
import time

from agent_framework import AgentContext, AgentMiddleware

log = logging.getLogger("pitch_insights.agents")
# The moment being written, so every log line and agent run can be tied back to it.
moment_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("moment_id", default="-")


class RunLogMiddleware(AgentMiddleware):
    """One structured log line per agent run: which agent, which moment, how long, how many
    tokens, and whether it failed. Prompts and replies are never logged."""

    async def process(self, context: AgentContext, call_next) -> None:
        started = time.perf_counter()
        error = None
        try:
            await call_next()
        except Exception as e:
            error = type(e).__name__
            raise
        finally:
            usage = getattr(context.result, "usage_details", None) or {}
            log.info(json.dumps({
                "event": "agent_run", "agent": getattr(context.agent, "name", None),
                "moment_id": moment_id_var.get(), "ms": round((time.perf_counter() - started) * 1000),
                "input_tokens": usage.get("input_token_count"), "output_tokens": usage.get("output_token_count"),
                "error": error,
            }))
