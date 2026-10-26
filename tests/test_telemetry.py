"""Telemetry is off by default and never carries user text.

The first property keeps `make up` free of an observability dependency; the second is the privacy
rule. The redaction test reads the call sites rather than trusting the authors.
"""

from __future__ import annotations

from db.settings import REPO_ROOT
from telemetry import enabled, setup
from telemetry import metrics as telemetry_metrics


def test_telemetry_is_off_without_an_endpoint(monkeypatch) -> None:
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    assert enabled() is False
    assert setup.configure("test-service") is False


def test_instrumenting_with_telemetry_off_is_a_no_op() -> None:
    class App:
        pass

    setup.instrument_app(App())  # must not raise or import an exporter


def test_the_metric_instruments_have_stable_names() -> None:
    for instrument in (
        telemetry_metrics.HTTP_REQUESTS,
        telemetry_metrics.GATEWAY_TURNS,
        telemetry_metrics.MCP_CALLS,
        telemetry_metrics.INGEST_RUNS,
        telemetry_metrics.ONCALL_CHECKS,
    ):
        # The API instrument is a proxy until a provider is set and exposes `_name` rather than
        # `name`; the name is still the stable identifier a dashboard is written against.
        assert instrument._name.startswith("hermes.")


def test_alert_and_freshness_state_can_be_updated() -> None:
    telemetry_metrics.set_alert_firing("ingest_unhealthy", True)
    telemetry_metrics.set_freshness_age("PL", 630)
    assert telemetry_metrics._alert_state["ingest_unhealthy"] == 1
    assert telemetry_metrics._freshness_age["PL"] == 630.0


def test_no_span_or_log_attribute_names_a_message() -> None:
    forbidden = (
        'set_attribute("message"',
        'set_attribute("user_message"',
        'set_attribute("chat_id"',
        'set_attribute("answer"',
    )
    for relative in ("agent/gateway/pipeline.py", "backend/app.py", "mcp_server/server.py", "agent/oncall/alerts.py"):
        source = (REPO_ROOT / relative).read_text(encoding="utf-8")
        for pattern in forbidden:
            assert pattern not in source, f"{pattern} in {relative}"


def test_the_backend_access_log_is_disabled_in_compose() -> None:
    compose = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "--no-access-log" in compose, "uvicorn would log /search/knowledge?q=<user text>"
