# On-call runbook

The `oncall` container is the on-call agent. It is a reader: `agent_readonly`, aggregate columns only,
no model, no upstream, no database write. It runs a 60 s tick that evaluates `ingest_unhealthy` and,
once a day at `ONCALL_DIGEST_HOUR`, writes a digest.

## Daily

```bash
make oncall-report          # copy /reports out of the container to data/oncall
docker compose exec -T oncall cat /reports/digest-<date>.md
make alert-check            # one evaluation against the real ledger, printed as JSON
docker compose exec -T oncall python -c "import urllib.request as u; print(u.urlopen('http://127.0.0.1:8300/health').read().decode())"
```

Read the digest top to bottom: overall freshness, per-competition ages, run outcomes, turn mix, eval
age. A `firing` alert is the first line; the reason string is the trigger.

The digest reads counts and statuses only. If you need the text of a turn, that is the dashboard's
`/turns` page with the admin token, not this job.

## The alert

`ingest_unhealthy` fires when:

| Reason | Trigger | Debounce |
| --- | --- | --- |
| `stale` | newest `succeeded`/`partial` run older than `ONCALL_STALE_MINUTES` (default 1560 = 26 h) | 2 checks |
| `repeated_failure` | the last 2 runs failed | immediate |
| `failure_pattern` | 3 of the last 5 runs failed | immediate |
| `stuck_run` | a `running` row older than 3 h | immediate |
| `never_succeeded` | runs exist but none ever succeeded | immediate |

It goes to a structured log line, `alerts.json`, and the `hermes_alert_firing` metric. Owner Telegram
is **off by default**; enabling it needs `ALERT_TELEGRAM_ENABLED=true`, a separate
`TELEGRAM_ALERT_BOT_TOKEN` and the owner's chat id, and sends only the fixed template (counters and
timestamps, no user text, notes or prompts). See decision 0010.

## Checks and drills

```bash
make alert-fire      # synthetic stale observation, no database; proves the rule and the template
make alert-drill     # real evaluation against the live ledger with a 1-minute threshold
make alert-state     # the stored state file
```

`make alert-fire` does not touch the live state. `make alert-drill` writes the drill state and then
the live container resolves it on its next tick; run `make alert-check` if you want to see the
resolve immediately.

## Bounds

- Read-only role (`agent_readonly`); no `user_message`, no `answer`, no note text in any query.
- No model. A model-backed answer verifier would be a new egress path and is out of scope.
- No upstream call. Ingestion is the only writer of football data.
- The weekly eval is **not** run here. The digest reports `eval_age_days`; running `make eval` stays a
  deliberate owner action because it sends the golden questions to `clef:cloud`.
