# Data model

What the database stores, how each table relates to `openapi.yaml`, and which columns exist only here. Written with
M1, because the schema is the one thing every later milestone reads.

The contract is the source of truth for what the API *serves*; `db/models.py` is the source of truth for what is
*stored*; `tests/contract_map.py` is the written-down mapping between the two, and `tests/test_contract_coverage.py`
fails in both directions when they drift apart — a contract property with nowhere to live, or a column no contract
property asks for.

## Tables

Eleven tables, one Alembic revision (`0001_init`, which is also the `schema_revision` that `HealthCheck` reports).
Everything is derived from the contract; nothing is scraped.

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

### Operations

| Table | Holds | Notes |
| --- | --- | --- |
| `ingest_runs` | `IngestRun`: the ledger of every collection run | `competitions` and `errors` are JSON: both are published as arrays of values, not as relations worth joining |
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
| `KnowledgeHit` | `knowledge_chunks` |
| `AgentTurn` | `agent_turns` |

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

1. **`agent_turns.route`, `route_source`, `route_confidence` are not in `openapi.yaml` v0.1.0.** `AGENTS.md` rule 10 and
   `_docs/product-spec.md` §7 require them, so the columns exist and the dashboard cannot see them yet. M3 adds them
   to `AgentTurn` and bumps the contract.
2. **`KnowledgeHit.source_file` path form.** The table stores corpus-relative paths (`policy/free-tier-delay-and-
   coverage.md`), matching the manifest and the schema's description "path inside the knowledge corpus". The contract's
   *example* is repo-relative (`hermes/agent-knowledge/competitions/championship.md`). One of the two should move;
   M3 decides, and the description is treated as authoritative until then.
3. **`matches.last_updated` vs `updated_at`.** `last_updated` holds the provider's own timestamp and `updated_at` when
   our ingestion wrote the row. The contract describes `last_updated` as the ingestion write time; the wording should
   be corrected when M3 exposes these fields.
4. **Draft notes are indexed.** The manifest's `status: draft` keeps the pipeline exercisable before the corpus is
   finished; M4 turns the seed note into a reviewed one, and `make check-notes` gates every change either way.
