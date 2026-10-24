"""Telemetry for the deployed replay server: requests, failures and timings in Application Insights.

Off unless APPLICATIONINSIGHTS_CONNECTION_STRING is in the environment (the Container App gets it from Key Vault),
so a laptop run sends nothing. Uses Azure Monitor OpenTelemetry, as Microsoft's guidance for Python says:
https://learn.microsoft.com/azure/azure-monitor/app/opentelemetry-enable?tabs=python

FastAPI is instrumented by hand instead of through the distro's default so that the many `send` and `receive`
spans of a replay's WebSocket (about ten messages a second) are left out: each connection is one span, not thousands.
Telemetry must never stop the server starting, so a failure here is logged and ignored.
"""

from __future__ import annotations

import logging
import os

log = logging.getLogger("pitch_insights")


def setup_telemetry(app) -> bool:
    connection_string = os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING", "").strip()
    if not connection_string:
        return False
    try:
        from azure.monitor.opentelemetry import configure_azure_monitor
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        logging.getLogger("azure").setLevel(logging.WARNING)  # the exporter logs every HTTP request at INFO
        os.environ.setdefault("OTEL_SERVICE_NAME", "pitch-insights-api")
        configure_azure_monitor(connection_string=connection_string, logger_name="pitch_insights",
                                instrumentation_options={"fastapi": {"enabled": False}})
        FastAPIInstrumentor.instrument_app(app, exclude_spans=["send", "receive"])
    except Exception as e:  # noqa: BLE001
        log.warning("telemetry is off: %s", type(e).__name__)
        return False
    log.info("telemetry to Application Insights is on")
    return True
