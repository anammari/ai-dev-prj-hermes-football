# Drill — stale-ingestion alert, 2026-10-27

**Purpose.** Prove `ingest_unhealthy` fires on a real ledger, is visible in Prometheus/Grafana, and
resolves — without waiting 26 hours and without inventing a fake database.

**Method.** The live ledger's newest `succeeded`/`partial` run was `2026-10-26T02:19:01Z`. The drill
ran the real evaluator once with `ONCALL_STALE_MINUTES=1` and `ONCALL_REQUIRED_BREACHES=1`, so the
same query that normally waits for 26 h fired on the real age. The live on-call loop was stopped for
the duration so its periodic `0` could not overwrite the drill's `1` before Prometheus scraped it.

## Timeline (UTC)

| Time | Event |
| --- | --- |
| 13:48:38 | drill container started; telemetry enabled for `hermes-oncall` |
| 13:48:40 | `alert.transition alert=ingest_unhealthy state=firing reason=stale age_minutes=689.6` |
| 13:49:00 | Prometheus `max(hermes_alert_firing)` = **1** |
| 13:50:00 | live `oncall` restarted; first check resolved: `state=ok`, `last_success_at=2026-10-26T02:19:01Z` |
| 13:50:08 | `/health` shows `alert: ok`, `last_check: 2026-10-26T13:50:00Z` |

## Commands and observed output

```text
$ docker compose stop oncall
$ OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4318 \
  docker compose run --rm -e ONCALL_STALE_MINUTES=1 -e ONCALL_REQUIRED_BREACHES=1 \
  oncall python -m agent.oncall --once
INFO telemetry.setup: telemetry enabled: service=hermes-oncall endpoint=http://otel-collector:4318
WARNING hermes.oncall: alert.transition alert=ingest_unhealthy state=firing reason=stale age_minutes=689.6 failures=0
INFO agent.oncall.notify: alert notification skipped: no alert bot configured
{
  "alert": {"name": "ingest_unhealthy", "state": "firing", "reason": "stale",
            "observed_minutes": 689.6, "consecutive_failures": 0, "breaches": 1},
  "last_success_at": "2026-10-26T02:19:01.705727+00:00",
  "recent_statuses": ["partial", "partial", "partial", "failed", "partial"]
}
```

```text
$ docker compose exec -T prometheus wget -qO- \
  "http://127.0.0.1:9090/api/v1/query?query=max(hermes_alert_firing)"
[... "value": ["1793022420", "1"]]
```

```text
$ docker compose start oncall
$ docker compose exec -T oncall python -c "import urllib.request as u; print(u.urlopen('http://127.0.0.1:8300/health').read().decode())"
{"status":"ok","service":"hermes-oncall","db":"configured","alert":"ok",
 "last_check":"2026-10-26T13:50:00.242815+00:00","last_digest":"2026-10-26","telegram":"disabled","error":null}
```

## What the drill found

- The evaluator fires on a real stale ledger in under two seconds with a 1-minute threshold; the
  26-hour production threshold is the same code path with a different number.
- The **stuck-run** condition was real, not hypothetical: the retained ledger had one orphaned
  `running` row (a killed container). The alert fired on it before the drill, which is how the
  startup recovery in `ingest/pipeline.py::close_orphaned_runs` was added. After recovery the ledger's
  recent statuses are `partial, partial, partial, failed, partial` and the alert is `ok`.
- The Telegram path is correctly silent with no alert bot configured; it logged the skip, not an
  error.
- The live loop's next check resolved the state, so a drill cannot leave production red.

## Evidence

- `hermes_alert_firing` in Grafana: <http://127.0.0.1:3001/d/hermes-freshness> (panel “Alert state over
  time”; the one-minute threshold run is the spike at 13:48 UTC).
- `alerts.json` and the daily digest: `make oncall-report` → `data/oncall/`.
- The drill wrote no database row and read no message text.
