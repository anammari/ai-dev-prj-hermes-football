# 0001 — The notes corpus: Markdown files, a manifest, and an index

- **Status:** Accepted (2026-10-10)
- **Milestone:** M1 (manifest + first note indexed), M4 (remaining notes authored and reviewed)
- **Related:** `_docs/product-spec.md` R-F6.1, R-F6.1a, R-F6.2, R-F6.4, R-F6.5; `_docs/scoping.md` §4, §8

## Context

The spec said which *topics* the notes must cover and how they are stored, embedded and re-indexed, but there was no
compiled list of the documents themselves:

- `R-F6.1` names five areas (competition formats, tiebreakers, promotion and relegation, the provider's coverage and
  delay policy, a glossary).
- `_docs/scoping.md` §4 names seven question classes the notes must answer — those five plus multi-hop rules
  questions and coverage limits — with worked examples.
- `R-F6.1a` requires the corpus to be written by hand, versioned in git and reviewed like code.
- `R-F6.4` decides staleness from a content hash.
- M1's acceptance criterion is "a note file can be indexed end to end", yet no note file had a name, an owner or a
  source citation.

## Decision

1. **The files are the source of truth:** `hermes/agent-knowledge/**/*.md`, written in English, versioned in git,
   changed through pull requests. Nothing generates them at runtime and nothing scrapes them.
2. **The compiled list is `hermes/agent-knowledge/manifest.yaml`**, one entry per note: `file`, `title`,
   `question_classes[]`, `competitions[]`, `source`, `owner`, `status`, `reviewed_at`.
3. **Each note repeats the same keys as YAML front-matter**, so a note still describes itself outside the manifest.
4. **Manifest and directory are checked against each other:** a test fails if a `.md` file has no entry, if an entry has
   no file, or if an entry cites no source. Any table rendered from the manifest is generated, never hand-edited.
5. **Postgres is a derived index, never the source.** `knowledge_chunks` rows are built from the files; dropping the
   index and rebuilding it must reproduce the same rows for the same corpus revision.
6. **Layout:** `hermes/agent-knowledge/<class>/<slug>.md`, for example `rules/championship-playoffs.md`.

Seed inventory — about ten files, one per question class from `_docs/scoping.md` §4, expanded in M4:

| Class | Notes to write |
| --- | --- |
| Competition formats | Championship promotion playoffs; the European competition format |
| Tiebreakers | Serie A level on points; Premier League goal difference |
| Qualification and relegation | Bundesliga relegation; Champions League qualification |
| Our data policy | Free-tier delay and coverage policy, carrying the delay measured in M2 |
| Coverage limits | Why lineups, odds and live scores are absent; which competitions are covered |
| Glossary | Aggregate, clean sheet, two-legged tie |
| Multi-hop rules | Fifth place plus a cup win, and the European place that follows |

## Alternatives considered

- **Database records as the source of truth** — breaks diffs and review, contradicts `R-F6.1a`, and duplicates
  `knowledge_chunks`.
- **A CSV inventory** — same objection, plus it drifts from the files the moment someone adds one.
- **Discovering notes by scanning the directory at index time** — the indexer would work, but nothing would say which
  notes *should* exist, their sources, or who owns them.

## Consequences

- A note that is not in the manifest is not shippable, and the corpus cannot rot silently.
- Every note costs one reviewable PR. That is the point: `_docs/scoping.md` §8 already states that the notes are
  written by hand and that the collection job only re-indexes the ones that changed.

## Verification

- Unit test: manifest and directory agree, every entry cites a source (runs in `make test`).
- M1 acceptance: one note is indexed end to end and appears in the generated table.
- M5 acceptance: editing a note changes the answer to the question that note covers.
