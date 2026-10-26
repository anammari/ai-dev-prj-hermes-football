# Observability — what runs, what it costs, and how to look

```bash
make obs-up                     # start the stack; Grafana on http://127.0.0.1:3001
make obs-down                   # stop it; app containers go back to telemetry-off
```

The stack is a separate Compose file with the `obs` profile, joined to the same project. `make up`
never starts it. Grafana is the only new host port and is bound to loopback with an anonymous
**Editor** role: Grafana 11.3 denies `datasources:explore` to a Viewer, so the Explore picker would be
empty. The dashboards stay provisioned and read-only, and an anonymous Editor cannot manage
datasources, users or org settings. **Never tunnel it, never expose it**, and do not add a login-less
public host.

| URL | What it shows |
| --- | --- |
| <http://127.0.0.1:3001/d/hermes-overview> | API, gateway, MCP, ingest, alert state, Loki logs |
| <http://127.0.0.1:3001/d/hermes-freshness> | data age per competition, alert timeline, on-call logs |
| <http://127.0.0.1:3001/explore> | Grafana Explore: pick Tempo for traces, Loki for logs, Prometheus for metrics |
| <http://127.0.0.1:3001/alerting/list> | no rules here by design: the alert is evaluated by `oncall`, not Grafana |

There is intentionally no host port for Prometheus, Loki or Tempo. Query them through Grafana, or
use `docker compose exec -T prometheus wget -qO- http://127.0.0.1:9090/-/healthy`.

## Signals

| Service | Metrics (`hermes_*`) | Traces | Logs |
| --- | --- | --- | --- |
| `backend` | `http_requests_total`, `http_duration_seconds_*` | one span per request, route template and status | JSON with `request_id`; the query string is not logged (`--no-access-log`) |
| `mcp-server` | `mcp_calls_total`, `mcp_duration_seconds_*` | `mcp.tool.call` per tool | tool name/status only |
| `hermes` gateway | `gateway_turns_total`, `gateway_duration_seconds_*` | `gateway.turn` + `mcp.tool.call`; no message text, no chat id | route/source/complexity |
| `ingest` | `ingest_runs_total`, `ingest_duration_seconds_*`, `ingest_upstream_calls_total` | `ingest.run` with status/calls/errors | run id/status/counters |
| `oncall` | `oncall_checks_total`, `oncall_digests_total`, `alert_firing`, `freshness_age_minutes` | `oncall` check/digest | alert transitions |

A metric is a number over time; a trace is one request's path; a log is a discrete event with
context. The alert is not a Grafana rule — `agent/oncall` evaluates the ledger and emits the metric,
so it still works when Grafana is down.

## Cost and retention

| Container | Limit | Notes |
| --- | --- | --- |
| `otel-collector` | 128 MB / 0.25 CPU | OTLP in, Prometheus/Loki/Tempo out |
| `prometheus` | 512 MB / 0.5 CPU | 7-day retention |
| `loki` | 256 MB / 0.25 CPU | 7-day retention |
| `tempo` | 256 MB / 0.25 CPU | 7-day retention |
| `grafana` | 256 MB / 0.5 CPU | provisioned dashboards, anonymous Editor (Explore needs it) |

≈1.4 GB RAM and 1.75 CPU while running; < 1 GB of volume per week at the default sampling. The
default is **100 % trace sampling** because this stack is low-traffic and a manual check must find the
request it just made; set `OTEL_TRACES_SAMPLER_ARG=0.1` on a busier host.

## Network and privacy

`otel-collector`, `prometheus`, `loki` and `tempo` are attached only to the internal `obs` network:
they can talk to each other and to the app services that send OTLP, and to nothing else. Grafana also
joins the default network because Docker does not publish a host port from an internal-only network;
its analytics, plugin download and update checks are disabled, and the two dashboards are provisioned
from this repository. No span, metric or log attribute carries a user message, an answer, a chat id,
a note passage or a token; `tests/test_telemetry.py` reads the call sites and `tests/test_oncall.py`
holds the query columns.

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| **Explore has no datasource picker, or the log says `Access denied … datasources:explore`** | the anonymous role is Viewer; Grafana 11.3 withholds Explore from it | `make obs-up` sets `GF_AUTH_ANONYMOUS_ORG_ROLE=Editor`; verify with `curl -s http://127.0.0.1:3001/api/access-control/user/permissions` |
| dashboards empty | app containers were not recreated with the endpoint | `make obs-up` (it recreates them and persists the endpoint in `.env`) |
| `hermes_*` series missing | sampling/export interval not elapsed | wait 15–30 s, then `make telemetry-smoke` |
| **a request produces no trace** | the app container has an empty `OTEL_EXPORTER_OTLP_ENDPOINT`, or you are looking at the last 5 minutes | `make telemetry-smoke` (it checks every container); set the range to Last 15 minutes and wait ~30 s |
| Grafana unreachable | the port is loopback-only, or Grafana is down | `docker compose ps grafana`; use `127.0.0.1:3001` |
| traces missing | the process was not configured | check `OTEL_EXPORTER_OTLP_ENDPOINT` in `docker compose config` |
| logs show a `q=` | an access log was re-enabled | the backend must run with `--no-access-log` |

## Manual checks

Run these in order after `make obs-up`; each has a visible result, not a promise.

1. **The dashboards load.** Open <http://127.0.0.1:3001/d/hermes-overview> and
   <http://127.0.0.1:3001/d/hermes-freshness>. Both render panels; the freshness panel's max age should equal the
   value from:
   ```bash
   set -a; . ./.env; set +a
   curl -s -H "Authorization: Bearer $API_AGENT_TOKEN" http://localhost:8000/meta/freshness | python3 -m json.tool | grep max_age
   ```
2. **One request, three signals.** Fire a request that prints its status, then look at the same request in Tempo,
   Loki and Prometheus with the range set to **Last 15 minutes**:
   ```bash
   set -a; . ./.env; set +a
   curl -s -o /dev/null -w 'freshness: %{http_code}\n' -H "Authorization: Bearer $API_AGENT_TOKEN" http://localhost:8000/meta/freshness
   ```
   It takes up to ~30 s for the trace and the log to appear (the SDK batches for 5 s, then Tempo/Loki flush); the
   metric is exported every 15 s. A silent curl that prints nothing is expected — add `-w` as above.
   - **Tempo:** Explore → Tempo → Search, Service Name `hermes-backend`; the trace `GET /meta/freshness` is there.
     Its span attributes include the route and status, not the query string.
   - **Loki:** Explore → Loki → Code, query
     `{service_name="hermes-backend"} |= "route=/meta/freshness"`; the line
     `request method=GET route=/meta/freshness status=200 duration_ms=… request_id=…` has a `traceid` you can open
     in Tempo.
   - **Prometheus:** Explore → Prometheus → Code, query
     `sum(hermes_http_requests_total{route="/meta/freshness"})` (or
     `hermes_http_requests_total{route="/meta/freshness", status="200"}`); the value is at least 1 and increments
     after another curl.
3. **A turn is a trace and a count.** `make ask Q="where are Arsenal in the table?"`, then search Tempo for
   `hermes-gateway-cli` / `gateway.turn`, and query `sum(hermes_gateway_turns_total)` in Explore → Prometheus. The
   span has `route`, `complexity`, `grounded`, `tool_calls`, `latency_ms` — no message.
4. **A tool call is counted.** Ask a notes question (`make ask Q="how does the championship playoff work?"`), then
   query `hermes_mcp_calls_total{tool="search_knowledge"}`. It increments and the call takes several seconds, which is
   the latency the timeout budget is sized for.
5. **Ingestion is visible.** `make itest` runs the ingestion integration test with a fake client; query
   `hermes_ingest_runs_total` and `hermes_ingest_upstream_calls_total`. A real `make ingest` produces the same series
   plus a 15–30 minute `ingest.run` trace.
6. **The alert fires and resolves.** `make alert-fire` prints a firing payload immediately (synthetic, no database).
   For the real path: stop the live loop (`docker compose stop oncall`), run `make alert-drill`, wait ~20 s, query
   `max(hermes_alert_firing)` (expect `1`), then `docker compose start oncall`; the next check resolves it to `0`.
   `make alert-state` shows the stored state and `make alert-check` prints one real evaluation.
7. **No user text in logs.** In Explore → Loki, run `{service_name="hermes-backend"} |= "search/knowledge?q="`: zero
   lines. The access log is disabled for exactly this reason.
8. **The on-call digest exists.** `make oncall-report`, then open `data/oncall/digest-<date>.md`: freshness per
   competition, run outcomes, turn mix, eval age — and no message text.
