# Golden-question evaluation

`make eval` answers every question in `golden-<date>.yaml` through the **shipped pipeline** - the same
router, safety gate, MCP tools, composer and verifier the Telegram bot uses - and stores the run in
Postgres and as an artifact here. The dashboard's `/evals` page reads it back through
`GET /evals/runs`.

The point is to turn "the agent feels good" into a number that can go down when someone breaks it,
and to make routing, retrieval, citations and completeness comparable across prompt versions.

## The set

`golden-2026-10-26.yaml`, 48 questions, versioned and hashed. It was written by an independent
reviewer who read only the product definition, the manifest and the notes; a second reviewer audited
the labels. The header records the author, and `tests/test_golden_set.py` enforces the mechanics:
counts, unique ids and messages, route/tool agreement, declared notes, headings that really exist in
those notes, and no message that names its own label.

| Route | N | What it must be |
| --- | --- | --- |
| `tool` | 16 | a stored number, date, score, table, form or freshness fact, served by exactly one of the seven data tools |
| `knowledge` | 16 | a written rule, format, tiebreaker, definition, coverage limit or policy, answered from a note |
| `clarify` | 8 | nothing in the message identifies a team, competition, match or rule |
| `refuse` | 8 | instruction override (3), fabricated/predicted fact (3), stored fact no tool serves (2) |

Each question carries `expected_route`, `expected_tool`, `expected_notes`, `expected_headings`,
`expected_facts` (a human rubric), `expected_terms` (the machine check, as alternative groups) and a
`rationale`. The two are kept apart on purpose: the rubric explains a failure to a reader, the terms
make the score reproducible without a judge.

## What a run measures

All deterministic. There is no model judge: a judge would need its own hand-labelled validation and a
new cloud egress path, and neither was signed off for M5 (decision 0008).

```json
{
  "routing": {
    "n": 48, "accuracy": 0.98, "errors": 0,
    "macro_precision": 0.97, "macro_recall": 0.97, "macro_f1": 0.97,
    "routes_with_support": ["tool", "knowledge", "clarify", "refuse"],
    "per_route": {"tool": {"precision": 1.0, "recall": 1.0, "f1": 1.0, "support": 16}, "...": {}},
    "tool": {"precision": 1.0, "recall": 1.0, "f1": 1.0},
    "per_class": {"standings": {"n": 3, "route": 3, "tool": 3}},
    "latency_p50_ms": 900, "latency_p95_ms": 2100
  },
  "retrieval": {"questions": 16, "recall_at_k": 1.0, "heading_recall": 0.95, "mean_top_score": 0.71},
  "answers": {"answerable": 32, "fact_coverage": 0.94, "citation_coverage": 1.0, "grounded_rate": 1.0},
  "gates": {
    "adversarial_refused": "3/3", "fabricated_refused": "3/3",
    "unsupported_refused": "2/2", "unsupported_with_reason": "2/2",
    "false_refusals": [], "database_to_notes": []
  },
  "runtime": {"composer": "beam:cloud", "thresholds": {"macro_f1": 0.9, "retrieval_recall": 0.9, "fact_coverage": 0.9}}
}
```

Definitions:

- **recall@k** - the share of `expected_notes` that appear in the passages the answer was grounded on.
  A note found twice counts once, and a failed retrieval scores 0, not "not applicable".
- **heading_recall** - the same for `expected_headings`; it catches the case where the right note was
  found but the wrong section was quoted.
- **fact_coverage** - the share of `expected_terms` groups with at least one alternative in the
  answer, matched on normalised whole words.
- **citation_coverage** - a knowledge answer must carry `Source:`; a database answer must carry the
  provider stamp. The deterministic composer writes both, so a miss is a composer regression.
- **grounded_rate** - the answer's own `grounded` flag, which the verifier sets, over the answerable
  questions. It is reported, not gated: the gate is the citation check.

## The gate

A run **passes** when all of these hold (floors are overridable in `.env`):

1. routing macro-F1 ≥ `EVAL_MIN_MACRO_F1` (0.90, the same target as the M4 gate);
2. zero false refusals and zero database-questions-answered-from-notes;
3. every `unsupported` refusal states `unsupported_tool`;
4. retrieval recall ≥ `EVAL_MIN_RETRIEVAL_RECALL` (0.90);
5. fact coverage ≥ `EVAL_MIN_FACT_COVERAGE` (0.90);
6. no answer is missing its citation.

A failed run is stored and stays on the scoreboard, red, with its reasons. That is the point.

**Smoke runs.** `--limit` and `--only-class` are diagnostics: they print metrics, do not evaluate the
gate and are never stored, because a four-question sample cannot answer a question about the set, and a
partial point on the set's series would lie. Macro averages are taken over the routes the run actually
exercised (`routes_with_support`), which on a full run is all four and identical to the M4 artifact's
arithmetic.

`make eval-self-check` proves the gate can fail: it scores a synthetic perfect run, then three
tampered ones (every route wrong, every fact missing, no citation anywhere) and fails if any tamper
still passes. It needs no model and no database, and it runs in `make test`.

## Comparability

A run records `set_name`, the set's SHA-256 and the prompt version. The dashboard draws one series per
set: two runs on different sets are not a trend. The two M4 holdout runs are imported with
`source: backfill` so the scoreboard has a baseline, and they report routing only - the M4 protocol
never measured retrieval, so those fields are **absent**, not zero.

## Files

- `golden-2026-10-26.yaml` - the questions.
- `model.py` - loading and label validation.
- `metrics.py` - scoring; pure, no clock, no model.
- `runner.py` - `make eval`, `--self-check`, and the artifact.
- `store.py` - the only writer of `eval_runs` / `eval_results`.
- `backfill.py` - imports the M4 artifacts.
- `runs/` - one JSON artifact per live run, committed deliberately (evidence, not cache).

## Limits

- Single turn: each question is routed on its own, exactly like the bot (no memory in M4/M5).
- The set is small enough to read. It is a regression suite, not a benchmark.
- Retrieval scores move with the corpus: a note edit re-indexes and can change recall without any
  code change. The run stores the set hash, not the corpus hash; a corpus change is visible in the
  artifact's `git_commit`.
- No adversarial generation: the 3 injection questions are fixed text, not a fuzzer.
