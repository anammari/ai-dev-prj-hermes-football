# Data model

What the database stores, how each table relates to `openapi.yaml`, and which columns exist only here. Written with
M1, because the schema is the one thing every later milestone reads.

The contract is the source of truth for what the API *serves*; `db/models.py` is the source of truth for what is
*stored*; `tests/contract_map.py` is the written-down mapping between the two, and `tests/test_contract_coverage.py`
fails in both directions when they drift apart — a contract property with nowhere to live, or a column no contract
property asks for.

## Tables

Thirteen tables across two Alembic revisions. `0001_init` established the M1 schema; `0002_ingestion_storage`
adds the M2 bronze store and scorer snapshots. The active revision is `0002_ingestion_storage`. Bronze payloads are
retained as JSON; only normalized rows feed serving tools.

### Catalog

| Table | Holds | Notes |
| --- | --- | --- |
| `competitions` | `Competition`, plus its `Coverage` block | The block is flattened into `coverage_*` columns: it is locally maintained and reviewed, and burying those flags in JSON would hide them from a migration diff |
| `seasons` | one row per competition season | Local table: the contract carries `season` as an integer. `year` is the provider's season number |
| `teams` | `TeamSummary` + `TeamDetail` extras | The id is the provider's, never generated here |
| `team_competitions` | `TeamDetail.competitions` | Local join table |
| `players` | squad members | Local table: the contract deliberately exposes only `squad_available`/`squad_size`, never a player list |

### Match data

| Table | Holds | Notes |
| --- | --- | --- |
| `matches` | `Match` | `score` is flattened (`score_full_time_home`, …), `referees` stays JSON because it is published as a list of objects with no key of its own and is never queried by field |
| `standings` | `StandingRow`s of one `StandingsTable` snapshot | `group` becomes `group_label` (SQL keyword) and `type` becomes `table_type`; `snapshot_date` keeps old snapshots queryable |
| `top_scorers` | normalized scorer rows per competition, season, and daily snapshot | Local serving data for the M2 requirement; each row links to a player and team |

### Operations

| Table | Holds | Notes |
| --- | --- | --- |
| `ingest_runs` | `IngestRun`: the ledger of every collection run | `competitions` and `errors` are JSON: both are published as arrays of values, not as relations worth joining |
| `raw_payloads` | bronze copy of each successful upstream response | Stores endpoint, request parameters, JSON payload, SHA-256 content hash, fetch time, and run id; never exposed to the agent. **Retention:** rows older than `RAW_PAYLOAD_RETENTION_DAYS` (default 30) are deleted at the end of each run (the current run is exempt), bounding it to roughly 30 days of runs instead of ~110k rows a year. `content_hash` is used for change detection: the run report counts payloads identical to an earlier one for the same endpoint |
| `agent_turns` | `AgentTurn`: what was asked, what was answered, how it was routed | `chat_id_hash` is salted; the raw Telegram id never reaches the database (`AGENTS.md` rule 6) |
| `knowledge_chunks` | the derived index of the notes corpus | `embedding vector(768)` on Postgres, `embedding_model`/`embedding_dim` per chunk, `content_hash` of the whole source file |

## The corpus is the source of truth, the table is an index

`hermes/agent-knowledge/**/*.md` are hand-written notes; `hermes/agent-knowledge/manifest.yaml` is the inventory
(`_docs/decisions/0001`). The indexer reconciles the table with the files:

- a file whose `content_hash` still matches is not re-embedded (`R-F6.4`);
- a changed file has its chunks replaced, never appended to;
- a `retired` note keeps its manifest entry and loses its chunks;
- a file that left the corpus loses its rows;
- a run that finds the manifest and the files disagreeing writes nothing.

`embedding_model` and `embedding_dim` are stored per chunk on purpose: changing either is a re-index, not an in-place
edit, and a query can tell that the index it is searching is not the index it thinks it is.

## Contract mapping

`tests/test_contract_coverage.py` checks this table by name. Column names are the contract's wherever the contract
names the same concept.

| Contract schema | Table |
| --- | --- |
| `Competition` (+ `Coverage`) | `competitions` |
| `TeamSummary`, `TeamDetail` | `teams` (+ `team_competitions`, `players`) |
| `Match` (+ `Score`, `ScoreLine`) | `matches` |
| `StandingRow`, `StandingsTable` | `standings` |
| `IngestRun` (+ inlined rows object) | `ingest_runs` |
| M2 scorer snapshot | `top_scorers` |
| M2 upstream response | `raw_payloads` |
| `KnowledgeHit` | `knowledge_chunks` |
| `AgentTurn` | `agent_turns` (including `route`, `route_source`, `route_confidence`, served since v0.2.0) |

Renamed, because SQL would rather not: `group` → `group_label`, `type` → `table_type` (standings), `chunk_id` → `id`,
`snippet` → `chunk_text`, `competition` → `competition_code`, `team`/`home_team`/`away_team` → `*_id`.

Nested objects are flattened with their parent's name: `Match.score.full_time.home` → `score_full_time_home`.

Computed, never stored: `StandingsTable.table`, `KnowledgeHit.score`, `TeamDetail.squad_available`/`squad_size`,
`TeamForm`, `HeadToHead` (the upstream aggregates are wrong — the contract says so), `FreshnessReport`, and the
response envelopes (`ResponseMeta`, `Pagination`, `ErrorResponse`, the `*List` schemas, `HealthCheck`).

## Postgres and the SQLite fallback

`R-F2.3` wants one code path, so the differences are confined to the migration and the query builder:

| | Postgres 16 | SQLite (dev only) |
| --- | --- | --- |
| `embedding` | `vector(768)` via pgvector | `TEXT` holding JSON, same `Embedding` type decorator |
| Similarity search | `<=>` against an HNSW index (`vector_cosine_ops`) | cosine in Python, same ranking, slower |
| Read-only agent role | `agent_readonly`: `SELECT`, plus default privileges so later tables stay read-only | no roles; the test suite checks the role on Postgres instead |
| Foreign keys | always enforced | `PRAGMA foreign_keys=ON` set by `db/session.py`, so a broken test cannot pass for the wrong reason |

## Open items

1. **Draft notes are indexed.** The manifest's `status: draft` keeps the pipeline exercisable before the corpus is
   finished; M4 turns the seed note into a reviewed one, and `make check-notes` gates every change either way.
2. **`standings.group_label` is dead weight today.** The API echoes a `group` only when every row of a table carries
   the same label, and no stored row does: the 1 752 rows on the retained volume are all league tables, and the
   provider's `group` field is absent from the free tier's standing rows. The column, the echo rule and its test stay
   because the contract has the field and a cup table would need it — but nothing depends on it yet.
3. **`standings.matchday` is always `NULL`.** The provider does not publish a matchday on standing rows, so
   `/competitions/{code}/standings?matchday=N` can only ever answer 404 against real data. The parameter is in the
   contract and implemented; when a real matchday source appears, the filter is already there.
4. **`/competitions/{code}/standings` takes no `season` *required* and no competition-wide season default.** The
   endpoint defaults to the competition's `current_season` from `competitions`, which is what ingestion last saw.
   Between a season rollover and the next run, "current" is one season behind; every answer says which season it
   served, so the agent can see it, but a stricter default would need the provider's calendar.
5. **`ingest_runs.competitions` is a JSON array, not a join table.** It reads well for a ledger and the contract
   exposes it as a list, but it cannot be joined or indexed by competition. If querying "when was PL last refreshed"
   ever becomes hot, this is the table to normalise (`/meta/freshness` computes it in Python today, over nine rows).
6. **The admin write operations have no queue behind them.** `POST /admin/ingest-runs` and
   `PATCH /admin/agent-turns/{turnId}/review` answer a contract-shaped 404 naming M5. Making the first one real needs
   a claimable queue the scheduler picks up; a request handler must not start an upstream run (`AGENTS.md` rule 3),
   so the write path is a scheduler concern before it is an API concern.
7. **The scorer snapshots have no agent-facing tool.** M2 stores normalised top-scorer rows, but `R-F4.1` exposes no
   scorer tool and the M3 API has no scorer operation, so a scorer question routes correctly and cannot be answered.
   The M3b spike labelled five such questions `route: tool` with no expected tool (decision 0003); M4 adds the tool or
   the bot refuses those questions.
