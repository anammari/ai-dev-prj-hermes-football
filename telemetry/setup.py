"""Provider setup, instrumentation and shutdown."""

from __future__ import annotations

import logging
import os

_configured = False
_enabled = False
_tracer_provider = None
_meter_provider = None
_logger_provider = None

LOGGER = logging.getLogger(__name__)


def enabled() -> bool:
    return bool((os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT") or "").strip())


def _endpoint(path: str) -> str:
    base = (os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT") or "").strip().rstrip("/")
    return f"{base}{path}"


def configure(service: str, *, version: str = "0.1.0") -> bool:
    """Wire traces, metrics and logs to the collector. Returns False when telemetry is off."""
    global _configured, _enabled, _tracer_provider, _meter_provider, _logger_provider
    if _configured:
        return _enabled
    _configured = True
    if not enabled():
        LOGGER.info("telemetry disabled: OTEL_EXPORTER_OTLP_ENDPOINT is unset")
        return False

    from opentelemetry import metrics, trace
    from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
    from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
    from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased

    resource = Resource.create(
        {
            "service.name": os.environ.get("OTEL_SERVICE_NAME") or service,
            "service.version": version,
            "deployment.environment": os.environ.get("DEPLOYMENT_ENVIRONMENT") or "local",
        }
    )

    # Low-traffic laptop: sample every trace by default so a manual inspection always finds the
    # request it just made. Set OTEL_TRACES_SAMPLER_ARG=0.1 on a busy host.
    sample_ratio = float(os.environ.get("OTEL_TRACES_SAMPLER_ARG") or 1.0)
    trace_provider = TracerProvider(
        resource=resource,
        sampler=ParentBased(TraceIdRatioBased(max(0.0, min(1.0, sample_ratio)))),
    )
    trace_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=_endpoint("/v1/traces"))))
    trace.set_tracer_provider(trace_provider)
    _tracer_provider = trace_provider

    reader = PeriodicExportingMetricReader(
        OTLPMetricExporter(endpoint=_endpoint("/v1/metrics")),
        export_interval_millis=15_000,
    )
    meter_provider = MeterProvider(resource=resource, metric_readers=[reader])
    metrics.set_meter_provider(meter_provider)
    _meter_provider = meter_provider

    logger_provider = LoggerProvider(resource=resource)
    logger_provider.add_log_record_processor(
        BatchLogRecordProcessor(OTLPLogExporter(endpoint=_endpoint("/v1/logs")))
    )
    handler = LoggingHandler(level=logging.INFO, logger_provider=logger_provider)
    logging.getLogger().addHandler(handler)
    _logger_provider = logger_provider
    _enabled = True
    LOGGER.info("telemetry enabled: service=%s endpoint=%s", resource.attributes["service.name"], _endpoint(""))
    return True


def instrument_app(app) -> None:
    """Instrument a FastAPI app. No-op when telemetry is off; health probes are not traced."""
    if not _enabled:
        return
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    FastAPIInstrumentor.instrument_app(app, excluded_urls="health,healthz,/openapi.yaml")


def instrument_http() -> None:
    if not _enabled:
        return
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

    HTTPXClientInstrumentor().instrument()


def get_tracer(name: str):
    from opentelemetry import trace

    return trace.get_tracer(name)


def get_meter(name: str):
    from opentelemetry import metrics

    return metrics.get_meter(name)


def shutdown() -> None:
    """Flush and stop the providers. Safe when telemetry was never configured."""
    global _configured, _enabled, _tracer_provider, _meter_provider, _logger_provider
    for provider in (_tracer_provider, _meter_provider, _logger_provider):
        if provider is not None:
            try:
                provider.shutdown()
            except Exception:  # noqa: BLE001 - shutdown must not fail an app close
                pass
    _tracer_provider = _meter_provider = _logger_provider = None
    _configured = False
    _enabled = False
