---
file: policy/free-tier-delay-and-coverage.md
title: What the free tier gives us, what it does not, and how old the data is
question_classes:
- data_policy
- coverage_limits
competitions: []
source: football-data.org coverage and API policies, plus the project's own free-tier
  probe in _docs/scoping.md section 3; URLs in _docs/notes-sources.md row 7.
owner: Ahmad Ammari
status: reviewed
reviewed_at: '2026-10-22'
---

# What the free tier gives us, what it does not, and how old the data is

This note explains what this bot can and cannot answer, and how old its answers are. It exists so the
bot can explain itself instead of guessing: when someone asks why it will not name the lineups, or
why a score is a few minutes behind, the answer is here rather than in the model's memory.

## What the free plan gives us

The plan is free and limited to **10 requests per minute**. Everything the bot knows about matches,
tables and squads is collected within that budget and stored locally before it is ever asked for.

Fixtures and results are available with filters by date, matchday and season. League tables are
available. On the provider's page the free tier advertises 12 competitions; the live API returned
**13** on 2026-10-10, the extra one being the Copa Libertadores. The competition list is read from
the API, never hardcoded.

## What it does not give us

Live in-play scores, betting odds, lineups and advanced statistics are paid features and are not
part of the normal plan. The odds field exists in the API response but only ever contains the words
"activate Odds-Package", so odds are never quoted. If a question needs one of these, the honest
answer is that the data is not available, not a guess.

Squads and top-scorer totals were returned by the free key on 2026-10-10 even though the pricing page
lists them as paid. They are treated as plan-dependent: the bot may use them only because ingestion
stored them, and must not promise they will always be there.

A competition outside the plan is refused by the API with "not within your permissions". When that
happens the bot says it has no data for that competition; it never shows an empty table, because an
empty table looks like a real answer.

## How old the data is

Scores and schedules are collected once a day, so an answer is as old as the last ingestion run, which
is always stamped on it. Measured on 2026-10-12/13 by polling one match (id 555033) from kick-off to
full time: the provider published the score while the match was still in play, and the final score
arrived with the `FINISHED` status, about **1.5 to 3 minutes** after the provider's own `lastUpdated`.
There was no window with a finished match and no score. The status also flipped back to `TIMED` for a
poll or two while the match was in play, so a single reading of a status can be wrong.

Re-measured live a day later on a different match (id 555032, still in play): ten polls gave a median
gap of **104 seconds** between the provider's `lastUpdated` and the moment the data was fetched, and
the score was already present while the match was `IN_PLAY`. `make score-delay` reproduces this — run
it during a match and it reports the gap on every poll, and says so when the match it was given
stopped being updated long ago. Quote the data timestamp with every score and never call it live.

## Why we count head-to-head records ourselves

The upstream head-to-head endpoint returns the meetings but its win, draw and loss counts are wrong
— a pair with three meetings came back as 0-0-0. This project counts the meetings from stored
results instead of repeating a number it knows to be broken.

## Source

football-data.org coverage and API policies, plus this project's probe recorded in `_docs/scoping.md`
section 3. The URLs are in `_docs/notes-sources.md` row 7.
