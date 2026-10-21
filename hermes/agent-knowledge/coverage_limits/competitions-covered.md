---
file: coverage_limits/competitions-covered.md
title: Which competitions the bot covers
question_classes:
- coverage_limits
competitions: []
source: football-data.org coverage and lookup tables, plus the live competition list
  recorded in _docs/scoping.md section 3; URLs in _docs/notes-sources.md row 9.
owner: Ahmad Ammari
status: reviewed
reviewed_at: '2026-10-22'
---

# Which competitions the bot covers

The bot covers the competitions the free plan exposes and ingestion has stored. On 2026-10-10 the
live API returned **13** competitions: the 12 advertised on the coverage page plus the Copa
Libertadores. The stored list is the source of truth, not the marketing page and not a hardcoded
twelve.

The 2026/27 set on the retained volume includes the Premier League, Championship, Bundesliga, Serie A,
La Liga, Ligue 1, Eredivisie, Primeira Liga, Brasileirão Série A, Champions League, Copa
Libertadores, European Championship and World Cup. A competition can be listed but have no table or
no scorers on the free tier; the bot says "no data" for that part rather than showing an empty table.

The provider filters the list by plan. If a competition is not in the stored list, the bot has no data
for it. It never invents a competition, and it never treats an unlisted competition as an empty table.

## What this note will not say

It does not promise coverage of a competition that the plan does not expose, and it does not list
every competition the provider sells on a paid tier.

## Source

football-data.org coverage page and lookup tables, linked from `_docs/notes-sources.md` row 9; the
live list is recorded in `_docs/scoping.md` section 3.
