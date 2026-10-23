---
file: coverage_limits/paid-features.md
title: Why lineups, live scores and odds are not available
question_classes:
- coverage_limits
competitions: []
source: football-data.org pricing and API policies; URLs in _docs/notes-sources.md
  row 8.
owner: Ahmad Ammari
status: reviewed
reviewed_at: '2026-10-22'
---

# Why lineups, live scores and odds are not available

The free plan covers delayed scores and schedules, fixtures, and league tables. The provider's
pricing page lists live scores, line-ups and substitutions, goal scorers and squads as paid
features, and odds and advanced statistics as separate add-ons. That is the advertised boundary.

The live probe on 2026-10-10 found squads and top-scorer totals reachable on the free key even though
the page lists them as paid. That does not make them guaranteed: the bot may answer a scorer question
only when a tool and stored rows exist, and it must never claim a paid feature is available just
because one probe succeeded.

What is always out of scope: in-play live scores, betting odds, lineups, and advanced statistics such
as xG. If asked for one, the answer is that the data is not available here, not a guess or a
prediction.

## What this note will not say

It does not quote odds, name a lineup, or describe a live in-play score.

## Source

football-data.org pricing and API policies, linked from `_docs/notes-sources.md` row 8, with the
2026-10-10 probe recorded in `_docs/scoping.md` section 3.
