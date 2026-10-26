# Threat model — Hermes Football

A one-page model of what is worth protecting, who can reach it, and which threats are mitigated by a
control rather than by good intentions. It is reviewed with the milestone; a new surface gets a row.

## Assets

| Asset | Why it matters |
| --- | --- |
| `agent_turns.user_message` / `.answer` | Real Telegram users' text; may contain personal detail. Masked on the dashboard by default and never an attribute on a metric or span. |
| Bearer and bot tokens | A token is a capability: the agent token reads every served table; the admin token writes the review columns. |
| Postgres data (matches, standings, turns, evals) | The product's grounding; corruption is an accuracy failure, not just a data failure. |
| The notes corpus | Hand-written, reviewed, cited; the only qualitative source. |
| Owner database credentials | The owner role can rewrite or drop everything. |
| Eval history | The evidence that the product did not regress; deleting or silently editing it destroys the audit trail. |
| Alert channel | A false or abusive alert costs operator trust; an over-privileged bot token can message anyone. |

## Actors and trust boundaries

| Actor | Trust | Boundary crossed |
| --- | --- | --- |
| Telegram user | untrusted, hostile input | Telegram → `hermes` (long polling) |
| Public review-bot user | untrusted, allow-all | Telegram → `hermes-review` |
| Tunnel visitor (demo) | untrusted, no login | Internet → `frontend:3000` |
| Owner | trusted, holds secrets | host → Compose |
| CI runner | semi-trusted, sees code | GitHub → repository |
| Dependency / image | semi-trusted | registry → build |
| Cloud model provider | receives only what an owner decision allows | `hermes` → `clef:cloud` / `beam:cloud` |
| Observability stack | local, no internet | app → collector → Prometheus/Loki/Tempo/Grafana |

## Threats and controls

| # | Threat | Control | Where it is proven |
| --- | --- | --- | --- |
| 1 | Prompt injection: a message tries to make the bot reveal instructions or call a tool it should not | `clef:cloud` safety label applied as a hard veto before any tool/note; no write tool; allowlisted MCP schema; refusals tested | `tests/test_agent_router.py`, `tests/integration/test_gateway_stack.py`, decision 0006 |
| 2 | Token leakage to a browser | server-only API client; no token in a served chunk; no off-origin browser request | `frontend/e2e/security.spec.ts`, decision 0008 |
| 3 | Token leakage to logs or an image | no token in a log line; `docker compose config` shows env-only secrets; gitleaks | `tests/test_api_security.py::test_secrets_are_not_logged`, `make scan-secrets` |
| 4 | Owner DB credential reaches an agent container | `backend` is handed an `agent_readonly` DSN; `mcp-server`/`hermes`/`frontend` have none; `oncall` is read-only | `tests/test_compose_policy.py`, `_docs/permissions.md` |
| 5 | The API grows a write path | one write operation, column-scoped grant, test that names the module and the columns | `tests/test_api_security.py`, `tests/integration/test_admin_review_stack.py` |
| 6 | Dashboard exposed beyond the demo | tunnel is manual and demo-only; no login; message text masked; no permanent host | `_docs/setup-and-review.md`, decision 0008 |
| 7 | Telemetry becomes a data exfiltration path | local collector only; no message text, chat id or note text in a span/log attribute; OTLP disabled unless configured; 10 % trace sampling | `tests/test_telemetry.py`, `observability/README.md` |
| 8 | Alert channel abused or over-privileged | separate alert bot token, one fixed template, one owner chat, disabled by default, metadata only | `agent/oncall/alerts.py`, decision 0010 |
| 9 | Supply-chain compromise | lockfiles, pinned images, actions pinned by SHA (see follow-up), Dependabot, `pip-audit`/`pnpm audit`/`trivy`, minimal `contents: read` CI permission | `.github/workflows/`, `security/scans/` |
| 10 | Upstream data poisoning or a bad provider payload | bronze payload hash, idempotent upserts, deterministic eval, a failed run stored red | `tests/test_ingest_pipeline.py`, `evals/golden/README.md` |
| 11 | Cost/abuse: a public bot is flooded or the free tier is exhausted | per-user interval, 500-char cap, allow-all only on the review bot, 10 req/min pacer, rate-limit counters | `tests/test_gateway.py`, `ingest/client.py` |
| 12 | A crashed run looks healthy | stuck `running` rows closed at startup; staleness alert; freshness report | `tests/test_oncall.py`, `ops/runbooks/ingest-stale.md` |
| 13 | CI receives a secret | no repository secrets in either workflow; throwaway DB values; `pull_request` jobs have no secrets | `.github/workflows/ci.yml` |

## Accepted risks (stated, not hidden)

- **No dashboard login.** The tunnel is demo-only and stopped after a demo; a permanent host would need
  authentication first.
- **Cloud routing is signed off, not local.** Every user message goes to `clef:cloud`; complex answers
  send tool results/note passages to `beam:cloud`. The simple path and all embeddings stay local
  (decisions 0003 and 0007). No other cloud path exists.
- **The alert bot token is a messaging capability.** It can send to one chat with a fixed template; it
  is disabled by default and enabled only with an owner decision.
- **Local observability only.** Grafana is bound to loopback and has no authentication; it must not be
  tunnelled.
- **No licence.** The repository is public without a licence, which is legally all-rights-reserved
  until the owner chooses one (decision 0009).

## Review triggers

Re-open this model when: a new container, tool, cron job, token or egress path is added; the dashboard
gets a login or a hostname; a cloud model or judge is introduced; CI gains a secret; or a scan is
allowlisted.
