# Gallery — the dashboard and the served API contract

Screenshots from a local `make up` on 26 October 2026, on the retained volume. The free tier is delayed, so every
timestamp here is the provider's, never the clock. Nothing in these pages is mocked: they are the app reading the same
`openapi.yaml` the agent reads.

## Dashboard

Seven server-rendered routes. The browser gets HTML and no token; each factual page carries its `data_as_of` and
source, because a number without its age is a guess.

### Freshness — the landing page

![The freshness page: a banner reading "Report as of 26 Oct 2026, 02:39 UTC, source: hermes-football ingestion ledger", three summary cards, and a table of all thirteen competitions with status, last run, age and row counts](assets/dashboard_freshness.png)

How old the stored data is, per competition, computed from the ingestion ledger. All thirteen are `fresh` with a 20
minute age; every `last run` is `partial` because EC's standings return 404 on the free tier — an expected state that
is shown, not painted green. `unknown` is a distinct verdict for a competition nothing has vouched for.

### Standings — a stored table, or the table as it stood

![The standings page: competition chips, season, snapshot date and matchday controls, then the Bundesliga table with position, played, won, drawn, lost, goals, signed goal difference, points and form](assets/dashboard_standings.png)

The Bundesliga table with a point-in-time snapshot selected. Only the total table is served; home and away splits stay
in the database. Goal difference is a signed integer, and the page names the snapshot its rows describe in the
provenance line below the fold.

### Fixtures and results — dates, scores and status

![The fixtures page: competition chips, from/to/status/team filters, then stored Bundesliga matches with kick-off in UTC, final scores, FINISHED badges and a details link](assets/dashboard_fixtures.png)

The season's stored matches, filtered by competition, date range, status or team. The note above the table is the point:
a fixture shown as scheduled may already have kicked off, and the stamp is the provider's, not the browser's clock.

### Agent turns — the audit log, with the one write

![The agent turns page: filters, then one turn showing route knowledge, source model with confidence 0.80, 8357 ms latency, grounded yes, a masked message, an answer citing the public note URL, and a review control with a status select and Save](assets/dashboard_agent_turns.png)

Every answer the bot gave, with the road it took. Message text is masked by default — the review bot is public, and this
page is one tunnel away from the internet. The review control is the only write in the product: admin token, two
columns, recorded on the row.

### Evaluation scoreboard — the golden set over time

![The evaluation scoreboard: summary cards (latest macro-F1 0.93, latest gate failed on fact coverage, five runs, two sets), a chart with the 0.90 target dashed and one line per set hash, and a table of five runs with macro-F1, accuracy, recall, fact coverage and gate](assets/dashboard_evals.png)

Five runs: three live on the 48-question golden set, all failing their gate on completeness or citations, and two
backfilled M4 holdout runs imported as the baseline. One line per set **hash**, because a score on a different sample is
not a continuation of the same trend; the hollow point is a run that failed. The red is the deliverable, not a defect.

### System — the API's own probe

![The system page: API ok on version 0.4.0, database ok on schema 0004, uptime, a contract card linking Swagger UI, and a table of the degraded states](assets/dashboard_system.png)

The one unauthenticated operation in the contract, and the page that still works when a token is misconfigured. Schema
revision `0004_evals_and_admin_review` is the same one the migration created.

## API contract

`openapi.yaml` is served verbatim at `/openapi.yaml` and rendered at `/docs`. The generated FastAPI document is
deliberately not published: one contract, one source of truth, checked by a drift test.

### The served description

![The top of Swagger UI: title "Hermes Football API", version 0.4.0 and OAS 3.0 badges, and the normative sections on the grounding contract, free-tier coverage, data freshness, authentication and MCP tools](assets/swagger_p1.png)

The document's own front matter: what every factual response must carry (`source`, `data_as_of`,
`upstream_delay_minutes`), why some fields are optional, the two tokens and their scopes, and the `x-mcp-tool`
convention that marks the operations the agent may call.

### The operations

![Swagger UI's operation list grouped by tag — meta, competitions, matches, teams — with a padlock on every protected operation](assets/swagger_p2.png)

Operations grouped by tag, with a padlock on each one that needs the bearer token. `/health`, `/openapi.yaml` and
`/docs` are the only open ones; the eval reads and the admin write carry no `x-mcp-tool`, so the agent can never read
its own score or review itself.

## The bot

![The Hermes Football avatar: a winged-helmet robot in a HERMES shirt holding a glowing football, inside a neon "HERMES FOOTBALL" ring, against a floodlit stadium with holographic stat panels](assets/telegram_bot_logo.jpeg)

The avatar of the public review bot, [@review_soccer_bot](https://t.me/review_soccer_bot).
