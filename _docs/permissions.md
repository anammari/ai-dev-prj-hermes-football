# Permissions — every capability, and the bound on it

`AGENTS.md` rule 8: a capability that is not written down is not shippable. This is the register. It covers the
services, the MCP tools, the dashboard, the admin write and the scheduled jobs, with the role or token each one uses
and the thing it may **not** do.

## Services

| Service | Reads | Writes | Reaches upstream | Bound |
| --- | --- | --- | --- | --- |
| `ingest` | the corpus | `competitions`, `matches`, `standings`, `top_scorers`, `ingest_runs`, `raw_payloads`, `knowledge_chunks` | yes, through `ingest/client.py` only | owner DB URL; the 10 req/min pacer; no request path imports it |
| `backend` | every served table as `agent_readonly` | `agent_turns.review_status`, `agent_turns.review_note` as `agent_admin` | no | one write operation, admin token, column-level grant |
| `mcp-server` | the backend API only | nothing | no | no database URL, no owner credentials, own optional token |
| `hermes` (gateway) | the MCP tools | `agent_turns` insert as `agent_writer` | `clef:cloud` (routing) and `beam:cloud` (complex answers) | no DB read role, no admin token, no Docker socket |
| `hermes-review` | the MCP tools | `agent_turns` insert as `agent_writer` | same as `hermes` | allow-all + 5 s/user + 500 chars; a **separate** bot token |
| `frontend` | the backend API only | the review endpoint, with `API_ADMIN_TOKEN` | no | `server-only` client; no database URL; no corpus mount |
| `oncall` | `ingest_runs`, `competitions`, `agent_turns` aggregate columns, `eval_runs` → `agent_readonly` | the `oncall-reports` volume: digest, `alerts.json` | Telegram only if `ALERT_TELEGRAM_ENABLED=true`, fixed template | no DB write, no message/answer text, no model, no upstream, no MCP |
| `otel-collector` | OTLP traces/metrics/logs | — | no | internal `obs` network only; no vendor endpoint |
| `prometheus` | the collector's exporter | `prometheus-data` | no | internal `obs` network; 7-day retention |
| `loki` | OTLP logs | `loki-data` | no | internal `obs` network; 7-day retention |
| `tempo` | OTLP traces | `tempo-data` | no | internal `obs` network; 7-day retention |
| `grafana` | Prometheus, Loki, Tempo | `grafana-data` | **loopback only** on `127.0.0.1:3001` | no login; anonymous Viewer; never tunnelled; plugin download and analytics disabled |
| `ollama` | — | the ollama volume | no egress for embeddings | local CPU-only build |
| `db` | — | — | — | the only stateful volume, plus `ollama-data`, `oncall-reports` and the four obs volumes |

## Database roles

| Role | Grants | Used by |
| --- | --- | --- |
| owner (`POSTGRES_USER`) | everything | migrations, ingestion, `make eval`'s store, the integration fixtures |
| `agent_readonly` | SELECT on all tables, including future ones | the API's request path |
| `agent_writer` | INSERT, SELECT on `agent_turns` | the gateway's turn log |
| `agent_admin` | SELECT on `agent_turns`; UPDATE on `review_status`, `review_note` | the review endpoint only |
| `agent_readonly` (on-call) | SELECT on every table; the queries name only aggregate columns | `oncall` |

No role may run DDL. No agent container holds the owner URL. The admin role cannot rewrite an answer it is reviewing:
the grant is per column.

## MCP tools (read-only, HTTP)

| Tool | Operation | May not |
| --- | --- | --- |
| `get_standings` | `getStandings` | write, reach upstream |
| `get_fixtures` | `listCompetitionMatches` | write, reach upstream |
| `get_match_result` | `getMatch` | write, reach upstream |
| `get_team_form` | `getTeamForm` | write, reach upstream |
| `get_head_to_head` | `getHeadToHead` | write, reach upstream |
| `get_top_scorers` | `getTopScorers` | write, reach upstream |
| `search_knowledge` | `searchKnowledge` | write, reach upstream |
| `get_data_freshness` | `getFreshness` | write, reach upstream |

The eval endpoints and the admin operations carry no `x-mcp-tool`: the agent must not read its own score, and it must
never be able to review itself.

## Dashboard

| Route | Operation(s) | May |
| --- | --- | --- |
| `/` | `getFreshness`, `listIngestRuns` | read |
| `/standings` | `listCompetitions`, `getStandings` | read |
| `/fixtures` | `listCompetitions`, `listCompetitionMatches`, `getMatch` | read |
| `/turns` | `listAgentTurns` | read; masks message text unless `DASHBOARD_SHOW_MESSAGES=true` |
| `/turns` (form) | `reviewAgentTurn` | **write**, admin token only, review columns only |
| `/evals`, `/evals/{id}` | `listEvalRuns`, `getEvalRun` | read |
| `/system` | `getHealth` | read (the operation is open by contract) |
| `/healthz` | — | static liveness; does not touch the API |

The browser holds no token. `frontend/src/lib/api/client.ts` is `server-only`, and `make e2e` asserts that no served
chunk contains the agent or admin token and that the browser makes no request off the dashboard origin.

## Scheduled and manual jobs

| Job | Where | May |
| --- | --- | --- |
| daily ingestion | `ingest` scheduler, `INGEST_SCHEDULE_*` | call upstream within the pacer; write the ledger and the loaded tables |
| re-index changed notes | `ingest/knowledge` | rewrite `knowledge_chunks` for changed files only |
| `make ingest` | one manual run | the same as the scheduler |
| `make score-delay` | one match poll | one upstream call; writes a ledger row with no competition scope |
| `make eval` | the eval runner | answer the golden questions; insert `eval_runs`/`eval_results` with the owner URL; **not** write `agent_turns` |
| `make eval-backfill` | the same store | insert the two M4 artifacts, marked `source: backfill` |
| daily digest | `oncall`, `ONCALL_DIGEST_HOUR` | read aggregate rows; write `digest-<date>.md`; no DB write, no message text |
| alert evaluator | `oncall`, every 60 s | read the ledger; write `alerts.json` and `hermes_alert_firing`; one Telegram message only if enabled |
| `make alert-fire` / `alert-drill` | one off `oncall` process | evaluate a synthetic or real observation; never wait for the schedule |
| CI (`ci.yml`) | GitHub runner | lint, test, scan, build; `contents: read`; no repository secret |
| nightly (`nightly.yml`) | GitHub runner | full-history secret scan, dependency drift; no project data |
| `make security-scan` | host + tool images | gitleaks, `pip-audit`, `pnpm audit`; advisory metadata only |
| `make scan-images` | host Docker socket | trivy over the built images; host-only, no Compose mount |

## Token map

| Token | Held by | Scope |
| --- | --- | --- |
| `API_AGENT_TOKEN` | backend (checks it), mcp-server, hermes, frontend (server) | every read operation |
| `API_ADMIN_TOKEN` | backend (checks it), frontend (server) | `reviewAgentTurn` only |
| `MCP_SERVER_TOKEN` | mcp-server (checks it), hermes | the MCP endpoint; optional, falls back to the agent token |
| `TELEGRAM_BOT_TOKEN` | hermes | main bot, allowlisted |
| `TELEGRAM_REVIEW_BOT_TOKEN` | hermes-review | public review bot; never the main token |
| `CHAT_HASH_SALT` | hermes | the chat-id hash; no raw id is stored |
| `AGENT_ADMIN_DB_PASSWORD` | backend only | the `agent_admin` login | in any agent container |
| `TELEGRAM_ALERT_BOT_TOKEN` | `oncall`, only when alerts are enabled | one fixed alert template to one owner chat | user text, notes, prompts; the main or review bot token |
| `ONCALL_DB_DSN` | `oncall` | the `agent_readonly` login | any write, any text column |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | app containers, only while `make obs-up` exported it | the local collector | a vendor endpoint |

## Volumes

`pgdata` and `ollama-data` hold the product state; `oncall-reports` holds the digest history;
`prometheus-data`, `loki-data`, `tempo-data` and `grafana-data` hold telemetry. None is a secret store,
and none is removed by the cleanup routine in `CLAUDE.md` without the owner's explicit confirmation.

## Egress

The only data egress is the routing/composition pair in `AGENTS.md` rule 10. Telemetry is local
(decision 0010). Owner-Telegram alert delivery is a separate, opt-in operational channel: counters and
timestamps only, disabled by default, with its own token. The backend is handed an `agent_readonly`
DSN, so the owner password does not enter the API container (`tests/test_compose_policy.py`).

Rotation: change the value in `.env` and recreate the service (`docker compose up -d --force-recreate <service>`).
No token is baked into an image; `docker compose config` is the check that a token arrived as an environment value.
