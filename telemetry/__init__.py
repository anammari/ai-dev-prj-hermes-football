"""Telemetry that is off unless a collector is configured.

The whole package is a no-op when `OTEL_EXPORTER_OTLP_ENDPOINT` is empty, which is the default on a
laptop and in the test suite. That matters for three reasons: `make up` must not depend on the
observability profile, a test must not need a collector, and a missing collector must never slow or
fail a user answer.

Signals are pushed over OTLP; no service exposes a `/metrics` route, because that would be an
undocumented operation and would break the contract-coverage test. The collector exposes Prometheus
for scraping instead.

Privacy rule: a span or log attribute may name a route, a tool, a status, a latency or an alert. It
may **not** carry a user message, an answer, a chat id, a note passage or a token. `tests/test_telemetry.py`
checks the call sites.
"""

from telemetry.setup import configure, enabled, get_meter, get_tracer, instrument_app, shutdown

__all__ = ["configure", "enabled", "get_meter", "get_tracer", "instrument_app", "shutdown"]
