# Data model

What Postgres stores, how it maps to `openapi.yaml`, and what is still open. `db/models.py` is the storage source of
truth; the contract is the serving source of truth; `tests/contract_map.py` holds the mapping.

## Tables

Thirteen tables, three Alembic revisions: `0001_init`, `0002_ingestion_storage`, `0003_agent_turn_writer` (head).

| Group | Tables | Notes |
| --- | --- | --- |
| Catalog | `competitions`, `seasons`, `teams`, `team_competitions`, `players` | Provider ids, not generated. Competition coverage flags are flattened columns. `players` is local; the API exposes only squad availability/size |
| Matches | `matches`, `standings`, `top_scorers` | Scores flattened; referees JSON. Standings keep daily snapshots, `group_label` and `table_type`. Scorers keep competition/season/snapshot |
| Operations | `ingest_runs`, `raw_payloads`, `agent_turns`, `knowledge_chunks`, `alembic_version` | Bronze payloads retained 30 days; turn rows use a salted chat hash; chunks store model, dimension, content hash |

## Roles

- `agent_readonly`: SELECT on all tables, default SELECT for future tables. Used by the API's agent path.
- `agent_writer`: INSERT/SELECT on `agent_turns` only, no default privileges. Used by the gateway.
- No agent DDL, no owner credentials in the MCP server or gateway.

## Corpus index

`knowledge_chunks` is derived from `hermes/agent-knowledge/` and its manifest; the files are the source of truth.
Re-indexing is content-hash driven: unchanged files untouched, changed files replaced, removed/retired files deleted.
See [`rag.md`](rag.md).

## Contract mapping

`tests/contract_map.py` maps every contract schema to a table/column, or records why it is not stored. The coverage
test fails if a contract property has no home or a column is not asked for. `tests/test_api_contract.py` validates
real responses against the contract's own schemas.

## Open items

1. **`standings.group_label`:** stored but the contract only exposes `group` when every row agrees. Serving grouped
   tables one at a time needs a contract parameter.
2. **`standings.matchday`:** stored; the contract exposes it but a multi-matchday table would need a clearer rule.
3. **`/meta/freshness`:** computed per request from nine rows in Python; normalise only if it becomes hot.
4. **Admin writes:** `POST /admin/ingest-runs` and `PATCH /admin/agent-turns/{id}/review` are contract-shaped 404s
   naming M5. A request handler must not start an upstream run; the write path needs a scheduler queue.
5. **Scorer snapshots:** exposed by `GET /competitions/{code}/top-scorers` and MCP `get_top_scorers`. The frozen
   routing holdout's four `unsupported` labels predate the tool and are historical.
