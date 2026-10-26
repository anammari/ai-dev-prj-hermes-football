# 0010 — Telemetry is local, and the alert channel is opt-in

**Status:** accepted (2026-10-26)
**Milestone:** M6
**Related:** 0003 (routing egress), 0007 (complex-answer egress), 0009 (M6 scope), `_docs/permissions.md`,
`security/threat-model.md`

## Context

M6 adds the first telemetry path and the first non-answer outbound channel. Both are easy to widen by
accident: a collector defaults to a vendor endpoint, a span records "just the query" because it is
useful in a debugger, or an alert bot is handed the main bot token because it is already in `.env`.
The project's egress policy allows exactly two cloud paths: the user message to `clef:cloud` and
complex-answer results to `beam:cloud`; note text and embeddings stay local. Any addition needs an
owner decision.

## Decision

1. **Telemetry is local and push-only.** Applications send OTLP to `otel-collector` on the internal
   `obs` network; Prometheus scrapes the collector's exporter, not the apps. There is no vendor
   endpoint, no `/metrics` route (which would be an undocumented operation) and no telemetry when
   `OTEL_EXPORTER_OTLP_ENDPOINT` is empty, which is the default. `otel-collector`, `prometheus`, `loki`
   and `tempo` are attached only to the internal network and cannot reach the internet.
2. **Grafana is the one exception at the network layer.** Docker does not publish a host port for a
   container attached only to an internal network, and the dashboard must be reachable at
   `127.0.0.1:3001`. Grafana therefore also joins the default network; its analytics, plugin download
   and update checks are disabled in Compose, and its two dashboards are provisioned from this
   repository. It is loopback-only and has no login, so it must never be tunnelled.
3. **No user text in telemetry.** A span or log attribute may carry a route, a tool, a status, a
   latency or an alert name. It may not carry a message, an answer, a chat id, a note passage or a
   token. The backend's uvicorn access log is disabled because it prints the query string of
   `/search/knowledge?q=...`; the app logs the route template instead. `tests/test_telemetry.py` reads
   the call sites and `tests/test_oncall.py` holds the query columns.
4. **Alert delivery is opt-in and metadata-only.** The default destinations are the log,
   `alerts.json` and `hermes_alert_firing`. Owner Telegram requires `ALERT_TELEGRAM_ENABLED=true`, a
   **separate** `TELEGRAM_ALERT_BOT_TOKEN` (never the main or review bot token) and
   `TELEGRAM_ALERT_CHAT_ID`; the body is the fixed template built from counters and timestamps. The
   owner signed this off on 2026-10-26 as an operational channel, not a new data path. It is off by
   default so an unconfigured stack cannot page anyone.
5. **Retention is short and stated.** Seven days for Prometheus, Loki and Tempo; 100 % trace sampling
   by default because the stack is low-traffic and a manual check must find the request it just made
   (`OTEL_TRACES_SAMPLER_ARG=0.1` on a busier host).

## Alternatives

- **A hosted observability vendor.** Rejected: a new egress path for prompts, tool output and logs.
- **Grafana Cloud / a public dashboard.** Rejected: no login and no owner sign-off for a public host.
- **Scraping app `/metrics`.** Rejected: a new undocumented route, contract drift, and a second
  instrumentation style next to OTLP.
- **Alertmanager + webhook.** Rejected for M6: one evaluator with a tested state machine is simpler,
  and the alert must work when the obs stack is down.
- **Reusing `TELEGRAM_BOT_TOKEN` for alerts.** Rejected: the on-call container would gain the ability
  to message any user of the product bot.

## Consequences

- A collector outage loses telemetry, not answers; the app treats an unreachable endpoint as a
  background failure, and the SDK is a no-op when the endpoint is unset.
- The alert still works with the obs stack down, because it reads Postgres.
- Grafana's default-network attachment is the one local-only exception and is recorded here rather
  than hidden in a Compose comment.
- A future vendor or a public dashboard is a new decision, not a configuration change.

## Verification

`tests/test_telemetry.py`, `tests/test_oncall.py`, `tests/test_compose_policy.py` (no socket, limits,
healthchecks, loopback Grafana), the manual egress test on the internal network, and the drill in
`ops/drills/2026-10-27-ingest-stale.md`.
