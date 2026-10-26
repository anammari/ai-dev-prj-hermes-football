# Capability table — every capability, its identity, and its bound

`AGENTS.md` rule 7: a new tool is a new row here. Rule 8: a capability that is not written down is
not shippable. This table is the security register; [`_docs/permissions.md`](../_docs/permissions.md)
is the same facts in the operational register, with the routes and tokens.

`tests/test_capability_table.py` parses this file and fails when a Compose service, an MCP tool or a
scheduled job is missing from it. A row here is a claim; the evidence column is what makes it
checkable.

## Services

| Capability | Surface | Identity | May | May not | Evidence |
| --- | --- | --- | --- | --- | --- |
| `db` | Compose service | owner | store state | be reached from the host | `docker-compose.yml` (no ports) |
| `ollama` | Compose service | none | embed locally on CPU | reach the internet | `tests/test_compose_policy.py`, decision 0005 |
| `backend` | Compose service, `:8000` | `agent_readonly`; `agent_admin` only for the review write; `API_AGENT_TOKEN` / `API_ADMIN_TOKEN` | serve the 19 contract operations; update two review columns | write football data, reach upstream, hold the owner DSN | `tests/test_api_security.py`, `tests/test_compose_policy.py` |
| `frontend` | Compose service, `:3000` | server-side `API_AGENT_TOKEN`, optional `API_ADMIN_TOKEN` | render seven routes; post the review form | send a token to the browser; read the database | `frontend/e2e/security.spec.ts` |
| `mcp-server` | Compose service, `:8100` | `API_AGENT_TOKEN` / `MCP_SERVER_TOKEN` | expose eight read tools over HTTP | write, run SQL, call upstream, hold a DB credential | `tests/test_mcp_server.py` |
| `hermes` | Compose service, `:8200` | writer role; router/composer tokens; bot token | route, retrieve, answer, insert one turn | read football tables, write anything else, hold an admin token | `tests/test_gateway.py`, `tests/integration/test_gateway_stack.py` |
| `hermes-review` | Compose service (profile `review`), `:8201` | separate bot token; writer role | answer the public review bot | use the main token; exceed 5 s/user or 500 chars | `_docs/setup-and-review.md` |
| `ingest` | Compose service | owner DSN | write bronze/silver/gold, index notes, run the schedule | be imported by request-handling code; call upstream outside the pacer | `tests/test_ingest_pipeline.py` |
| `oncall` | Compose service, `:8300` internal | `agent_readonly` DSN; optional alert bot token | read aggregate ledger/turn/eval state; write reports and alert state | write the database, run ingestion, call a model, read message text | `tests/test_oncall.py`, `tests/integration/test_oncall_stack.py` |
| `otel-collector` | Compose profile `obs` | none | receive OTLP, export to Prometheus/Loki/Tempo | reach the internet, read the database | `observability/otel/collector.yaml` |
| `prometheus` | Compose profile `obs` | none | scrape the collector, retain 7 days | scrape an app directly, read the database | `observability/prometheus/prometheus.yml` |
| `loki` | Compose profile `obs` | none | store logs, retain 7 days | read the database | `observability/loki/loki-config.yaml` |
| `tempo` | Compose profile `obs` | none | store traces, retain 7 days | read the database | `observability/tempo/tempo.yaml` |
| `grafana` | Compose profile `obs`, `127.0.0.1:3001` | anonymous Editor (local only) | show metrics/logs/traces and the alert panel | be published off loopback, hold a project token | `docker-compose.observability.yml` |

## Tool and test targets (never started by `make up`)

| Capability | Identity | May | May not | Evidence |
| --- | --- | --- | --- | --- |
| `models` | none | pull the pinned embedding model | reach any other network destination | `Dockerfile.ollama` |
| `migrate` | owner | apply migrations | serve traffic | `db/migrations` |
| `tests` | owner + agent roles | run the suite, read fixtures | be a runtime service | `tests/` |
| `frontend-e2e` | no DB | run Playwright and pnpm | hold a DB credential | `frontend/e2e/Dockerfile` |

## MCP tools (read-only, over HTTP)

| Tool | Operation | May | May not |
| --- | --- | --- | --- |
| `get_standings` | `getStandings` | read a stored table | write, reach upstream |
| `get_fixtures` | `listCompetitionMatches` | read stored fixtures | write, reach upstream |
| `get_match_result` | `getMatch` | read one match | write, reach upstream |
| `get_team_form` | `getTeamForm` | read stored results | write, reach upstream |
| `get_head_to_head` | `getHeadToHead` | read stored meetings | write, reach upstream |
| `get_top_scorers` | `getTopScorers` | read a scorer snapshot | write, reach upstream |
| `search_knowledge` | `searchKnowledge` | read indexed note passages | write, reach upstream, send note text to a cloud model |
| `get_data_freshness` | `getFreshness` | read the freshness report | write, reach upstream |

The eval reads and the admin operations carry no `x-mcp-tool`: the agent cannot read its own score and
cannot review itself.

## Scheduled and manual jobs

| Job | Where | May | May not | Evidence |
| --- | --- | --- | --- | --- |
| daily ingestion | `ingest` scheduler | call upstream inside the 10 req/min pacer; write the ledger and loaded tables | run from a request handler | `ingest/scheduler.py` |
| re-index changed notes | `ingest/knowledge` | rewrite `knowledge_chunks` for changed files | generate a note at runtime | `make index-notes` |
| `make ingest` | one manual run | the same as the scheduler | bypass the pacer | `Makefile` |
| `make score-delay` | one match poll | one upstream call per poll; write a ledger row | present delayed data as live | `ingest/__main__.py` |
| `make eval` | eval runner, owner DSN | answer the golden set; insert `eval_runs`/`eval_results`; call `clef:cloud` for routing | write `agent_turns`; use a model judge | `evals/golden/README.md` |
| `make eval-backfill` | the same store | import the two M4 artifacts as `backfill` | invent a metric the protocol did not measure | `evals/golden/backfill.py` |
| on-call digest | `oncall` | read aggregate rows; write a digest file and a metric | write the database, read message text, call a model | `agent/oncall/` |
| alert evaluator | `oncall` | read the ledger; write alert state; emit one Telegram message **only if enabled** | send user text, notes or prompts anywhere | `agent/oncall/alerts.py` |
| CI (`ci.yml`) | GitHub runner | read code and lockfiles; run tests; build images | receive a repository secret, run the eval or the router suite | `.github/workflows/ci.yml` |
| nightly (`nightly.yml`) | GitHub runner | audit dependencies and scan history | receive project data or prompts | `.github/workflows/nightly.yml` |
| `make security-scan` | host + tool images | read the repository and public advisories | send source to a project service | `Makefile` |

## Tokens

| Token | Held by | Scope | Never |
| --- | --- | --- | --- |
| `API_AGENT_TOKEN` | backend, mcp-server, hermes, frontend (server) | every read operation | in the browser, in an image layer |
| `API_ADMIN_TOKEN` | backend, frontend (server) | `reviewAgentTurn` only | reachable by the agent |
| `MCP_SERVER_TOKEN` | mcp-server, hermes | the MCP endpoint; falls back to the agent token | in a log or a prompt |
| `TELEGRAM_BOT_TOKEN` | hermes | the main allowlisted bot | in `hermes-review` |
| `TELEGRAM_REVIEW_BOT_TOKEN` | hermes-review | the public review bot | in `hermes` |
| `TELEGRAM_ALERT_BOT_TOKEN` | oncall, only when alerts are enabled | one fixed alert template to one chat | user text, notes, prompts |
| `CHAT_HASH_SALT` | hermes, hermes-review | the chat-id hash | in the database |
| `AGENT_ADMIN_DB_PASSWORD` | backend | the `agent_admin` login | in the agent containers |
