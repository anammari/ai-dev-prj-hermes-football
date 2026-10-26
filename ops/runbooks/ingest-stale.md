# Runbook — `ingest_unhealthy` (stale or failing ingestion)

The alert means the served data may be older than the dashboard's own freshness threshold, or the
ingestion ledger has stopped making progress. It does **not** mean the bot is down: a bot reading
yesterday's table can still answer, with yesterday's timestamp.

## 1. Confirm, do not assume

```bash
make alert-state
make alert-check
curl -s -H "Authorization: Bearer $API_AGENT_TOKEN" http://localhost:8000/meta/freshness | python3 -m json.tool | head -40
docker compose ps ingest backend db ollama
docker compose logs --tail=80 ingest
```

- `stale` + a healthy `ingest` container: the scheduler may not have reached its window, or a run is
  in flight.
- `repeated_failure` / `failure_pattern`: read the latest `ingest_runs.errors`; a 403/404 on an
  optional sub-resource is expected (`partial`), not a failure.
- `stuck_run`: a previous container was killed mid-run. The scheduler closes orphaned rows on start;
  restart it: `docker compose restart ingest`.
- `never_succeeded`: check `UPSTREAM_API_KEY` and the upstream status before anything else.

## 2. Fix the cause, then re-run

```bash
make ingest                 # one manual run, through the same pacer and ledger
docker compose logs -f --tail=100 ingest
```

A run takes 15–30 minutes at 10 req/min. Do not start a second one; the free tier is a shared budget.
`make ingest` writes the same ledger rows the scheduler does, and the next alert check will see the
outcome.

## 3. Verify

```bash
make alert-check            # expect state ok and a low observed_minutes
curl -s -H "Authorization: Bearer $API_AGENT_TOKEN" http://localhost:8000/meta/freshness | python3 -c \
  "import sys,json; d=json.load(sys.stdin); print(d['overall_status'], d['max_age_minutes'])"
```

The dashboard `/` should show the same verdict. If the alert is still firing, the reason tells you
which condition; a resolved alert keeps its reason in the log for the postmortem.

## 4. Record it

Append a dated note to `ops/drills/` (or a new incident file) with: what fired, when, the observed
value, the cause, the action, and the time it resolved. That file is the evidence that the alert was
actionable rather than decorative.
