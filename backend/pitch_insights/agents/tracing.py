"""Tracing: OpenTelemetry traces from Agent Framework to Application Insights.

Each agent run, model call, retry, groundedness check and safety check shows up as a span,
tied to its moment, so a handoff or a fallback can be followed in the Foundry project's
Tracing page or in Application Insights. Follows Agent Framework's observability guide:
https://learn.microsoft.com/agent-framework/agents/observability

Prompts and replies are never recorded (sensitive data stays off), only which agent ran, for
which moment, how long it took, the tokens used and the outcome.

Off unless APPLICATIONINSIGHTS_CONNECTION_STRING is set in .env.
"""

from __future__ import annotations

import logging
import os

from opentelemetry import trace

log = logging.getLogger("pitch_insights.agents")


def setup_tracing(settings, service_name: str = "seize-the-game") -> bool:
    """Send traces to Application Insights. Returns False (and does nothing) if it isn't configured."""
    if not settings.appinsights:
        return False
    import truststore
    from agent_framework.observability import enable_instrumentation
    from azure.monitor.opentelemetry import configure_azure_monitor

    # The exporter verifies certificates with its own bundled list; on a network that inspects
    # HTTPS that fails, so use the operating system's store, as the chat client does.
    truststore.inject_into_ssl()
    logging.getLogger("azure").setLevel(logging.WARNING)  # the exporter logs every HTTP request at INFO
    os.environ.setdefault("OTEL_SERVICE_NAME", service_name)
    configure_azure_monitor(connection_string=settings.appinsights, logger_name="pitch_insights")
    enable_instrumentation(enable_sensitive_data=False)
    log.info("tracing to Application Insights is on")
    return True


def flush_tracing() -> None:
    """Send any spans still waiting, before a script exits."""
    provider = trace.get_tracer_provider()
    if hasattr(provider, "force_flush"):
        provider.force_flush()
