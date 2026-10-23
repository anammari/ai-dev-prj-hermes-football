# Notes sources — the URLs behind the knowledge corpus

What this file is: the checked source list for the hand-written notes in `hermes/agent-knowledge/`.
The notes are the source of truth for the qualitative answers (`R-F6.1`, `R-F6.1a`); this table says where
each one comes from, so a reviewer can open the source and check the note against it.

It is a companion to two existing files, not a replacement for either:

- `hermes/agent-knowledge/manifest.yaml` stays the inventory: file, title, classes, owner, status, short citation.
- This table holds the long, checkable part: URL, publisher, season and the date the URL was opened.

`_docs/decisions/0001` still governs the corpus (the files are the truth, the manifest lists them). This table
adds the missing source URLs without changing that decision.

## Rules

1. One row per planned note. The file path is the path the note will have under `hermes/agent-knowledge/`.
2. Official publisher only: the competition's regulator, league or the data provider. Wikipedia, news sites
   and stats aggregators are allowed while *finding* a source, never as the cited source.
3. A URL is opened and checked when the note is written. The date goes in the note's `reviewed_at` and in the
   note's `source` text. A dead or changed URL is a note change, not a silent omission.
4. Rules are season-stamped. Every row below is the 2026/27 season; a rollover means re-checking the row and
   updating the note, not assuming last season's text still holds.
5. The corpus is English. A non-English source is quoted in English translation and the note keeps the
   document reference (for example the FIGC communiqué number and date).
6. Where a provider page and the live API disagree, the live API wins for what the bot can actually answer,
   and the note says both. The free-tier probe is recorded in `_docs/scoping.md` §3.
7. Translation happens at authoring time, not at query time. The author reads the official source and writes the
   English note; a quoted clause appears in English translation and is reviewed with the note. No translation API,
   no runtime translation service and no egress: only English note text is chunked and embedded. A local model may
   draft a translation, but a human reviews it and the note remains the source of truth.

## Planned notes and sources

Status is what a browser-like fetch returned on **2026-10-21**: `200 HTML`, `206 PDF` (a ranged request for a
PDF), or `200 JS` for an official page that renders its article with JavaScript. A `200 JS` page is valid for a
human; a scripted check sees only the app shell.

| # | Note file | Class | What the source fixes | Source (official) | Also checked | Status |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | `formats/championship-playoffs.md` | formats | Six-team play-off from 2026/27: QF 5th v 8th and 6th v 7th (higher club at home), two-legged semi-finals (3rd v lowest remaining, 4th v highest remaining), Wembley final; seven matches | [EFL Regulations 2026/27 (PDF)][efl-regs], Regulation 10.1.1 and its Guidance | [EFL statement, 5 Mar 2026][efl-statement]; [EFL regulations index][efl-index] | 206 PDF |
| 2 | `formats/european-competitions.md` | formats | League phase: each club plays eight opponents, four home and four away; knockout ties are two legs decided on aggregate | [UEFA Champions League Regulations 2026/27, Article 17][uefa-art17] | [Article 20, knockout phase][uefa-art20]; [UEFA 2026/27 explainer][uefa-explainer] | 200 JS |
| 3 | `tiebreakers/serie-a-level-points.md` | tiebreakers | 2026/27: level on points for 1st is a single play-off at the better-ranked club, penalties if level; 17th v 18th is two legs on aggregate, penalties if level; more than two clubs use the *classifica avulsa*; no play-off if a club is in a UEFA final | [FIGC Communiqué 244/A, 27 May 2026 (PDF)][figc-244] | [Lega Serie A documentazione][seriea-docs] | 206 PDF |
| 4 | `tiebreakers/premier-league-goal-difference.md` | tiebreakers | Table order is points, then goal difference, then goals scored; if a decisive place is still level, Rule C.17 applies: head-to-head points, away goals in those matches, then a neutral play-off | [Premier League Handbook 2026/27 (PDF)][pl-handbook], Rule C.17 | [Premier League publications][pl-publications] | 206 PDF |
| 5 | `qualification_relegation/bundesliga-relegation.md` | qualification_relegation | Bottom two go down; 16th in the Bundesliga plays 3rd in Bundesliga 2 over two legs, European Cup system; the club with fewer free days before the first leg hosts the second | [DFL glossary: relegation play-offs][dfl-glossary] | [Bundesliga FAQ: promotion and relegation][bundesliga-faq] | 200 HTML |
| 6 | `qualification_relegation/champions-league-qualification.md` | qualification_relegation | The access list: which domestic places and cup winners enter which competition and round | [UEFA Champions League Regulations 2026/27, Annex A][uefa-annex-a] | [UEFA access list (men's)][uefa-access-list] | 200 JS |
| 7 | `policy/free-tier-delay-and-coverage.md` *(existing seed note — update its source line)* | data_policy, coverage_limits | Advertised plan: free, 12 competitions, delayed scores and schedules, fixtures, tables, 10 calls/minute | [football-data.org coverage][fd-coverage] | [API policies: request throttling][fd-policies]; internal probe in `_docs/scoping.md` §3 | 200 HTML |
| 8 | `coverage_limits/paid-features.md` | coverage_limits | What the advertised free tier withholds: live scores, line-ups, goal scorers, squads; the delay is not documented | [football-data.org pricing][fd-pricing] | [API policies][fd-policies] | 200 HTML |
| 9 | `coverage_limits/competitions-covered.md` | coverage_limits | The free competition list and the league codes used to address it | [football-data.org coverage][fd-coverage] | [Lookup tables: league codes][fd-lookup] | 200 HTML |
| 10 | `glossary/aggregate-two-legged-tie.md` | glossary | Aggregate score, two legs, no away-goals rule | [UEFA Champions League Regulations 2026/27, Article 20][uefa-art20] | — | 200 JS |
| 11 | `glossary/clean-sheet.md` | glossary | No regulator defines the term; the official stats page shows its usage only. The definition is editorial (open item 1) | [Premier League clean sheets][pl-clean-sheets] | — | 200 HTML |
| 12 | `multi_hop/fifth-place-and-cup-winner.md` | multi_hop | Top four enter the UCL; a fifth UCL place can come from the European Performance Spot; 5th (or 6th) takes the UEL place; FA Cup winners enter the UEL league phase; EFL Cup winners enter the Conference League play-off; a cup winner already in the top five passes the place down | [Premier League: European qualification explained][pl-europe] | [UEFA access list (men's)][uefa-access-list] | 200 HTML |
| 13 | `tiebreakers/la-liga-head-to-head.md` | tiebreakers | Two clubs level: head-to-head goal difference, then overall goal difference, goals scored, fair play, a neutral match; three or more: a mini-league of the matches between them, then the same list | [RFEF Circular 84, 2026/27 (PDF)][rfef-84], Article 10 | [LaLiga regulatory page][laliga-normative] | 206 PDF |

[efl-regs]: https://images.gc.eflservices.co.uk/c99e4490-a070-11f1-b53b-9be1de328ad3.pdf
[efl-statement]: https://www.efl.com/news/2026/march/05/efl-statement--sky-bet-championship-play-off-format/
[efl-index]: https://www.efl.com/document/regulations/
[uefa-art17]: https://documents.uefa.com/r/Regulations-of-the-UEFA-Champions-League-2026/27/Article-17-Match-system-league-phase-Online
[uefa-art20]: https://documents.uefa.com/r/Regulations-of-the-UEFA-Champions-League-2026/27/Article-20-Match-system-knockout-phase-Online
[uefa-annex-a]: https://documents.uefa.com/r/Regulations-of-the-UEFA-Champions-League-2026/27/II-Competition-System-Online
[uefa-explainer]: https://www.uefa.com/uefachampionsleague/news/02a6-20d57cfcd03e-407c22a7f465-1000--2026-27-champions-league-teams-dates-draws-format-final/
[uefa-access-list]: https://www.uefa.com/nationalassociations/uefarankings/accesslist/uefaeuropaleague/
[figc-244]: https://files.figc.it/version/c:ZmUzYzk0MzUtMzU0Zi00:YTk3YzZiZGEtYmExYi00/244%20-%20Deroga%20art.%2051%20NOIF%20-%20Determinazione%20classifica%20Campionato%20Serie%20A%20ss%202026%20-%202027.pdf
[seriea-docs]: https://www.legaseriea.it/lega-serie-a/documentazione
[pl-handbook]: https://resources.premierleague.pulselive.com/premierleague/document/2026/07/31/8a890ff9-176c-4364-a8ff-e08f995e2c86/TM2040_PL-Handbook-and-Collateral-2026-27_Digital_31.07.pdf
[pl-publications]: https://www.premierleague.com/en/media/publications
[dfl-glossary]: https://www.bundesliga-group.com/glossary/relegation-play-offs/
[bundesliga-faq]: https://www.bundesliga.com/en/faq/what-are-the-rules-and-regulations-of-soccer/how-does-promotion-and-relegation-work-in-the-bundesliga-10645
[fd-coverage]: https://www.football-data.org/coverage
[fd-pricing]: https://www.football-data.org/pricing
[fd-policies]: https://docs.football-data.org/general/v4/policies.html
[fd-lookup]: https://docs.football-data.org/general/v4/lookup_tables.html
[pl-clean-sheets]: https://www.premierleague.com/en/clean-sheets-25-26
[pl-europe]: https://www.premierleague.com/en/european-qualification-explained
[rfef-84]: https://rfef.es/sites/default/files/pdf/circulares/1._Circular_84_-_CNL_Primera_y_Segunda_Division___Anexo.pdf
[laliga-normative]: https://www.laliga.com/en-GB/transparency/normative

Two "also checked" pages reject a plain command-line fetch while opening in a browser: the UEFA news explainer
and the UEFA access-list page refuse the connection to a script, and the Bundesliga FAQ answers `403`. They are
listed because a human can read them; a future automated check must not read the script's `000` or `403` as a dead
link.

## Provider facts versus the live probe

The provider's own pages and the live API do not agree, and the notes must not paper over it. The probe in
`_docs/scoping.md` §3 is the record of what the bot can actually answer:

| Fact | Provider page says | Probe on 2026-10-10 found | What the note must say |
| --- | --- | --- | --- |
| Free competitions | 12 ([pricing][fd-pricing], [coverage][fd-coverage]) | **13**, the extra being the Copa Libertadores | The list is plan-filtered and checked live; never hardcode 12 |
| Squads | Paid ("Deep Data", €29/mo) | Returned on the free key (24 Arsenal players, 48 Fluminense) | Available today, but the plan page says otherwise; treat as plan-dependent |
| Top scorers | Paid ("Deep Data") | Returned on the free key | Stored; exposed by `get_top_scorers` since M4 |
| Odds | Paid add-on | Field present but only "activate Odds-Package" | Never quote odds |
| Head-to-head counts | Published by the endpoint | Win/draw/loss counts wrong (0–0–0 for a pair with three meetings) | Count meetings from stored results |
| Score delay | Not documented | About 1.5–3 minutes; median 104 s over ten polls on match 555032 | Quote the measurement and `make score-delay`; never call the score live |

## Open items

1. **Clean sheet has no official definition — resolved 2026-10-22.** The note is written as an editorial
   definition citing official *usage* (row 11), and it says no regulator defines the term. It is not presented as a
   competition rule.
2. **The provider is wrong about its own free tier.** Rows 7–9 must describe the probe, not repeat "12
   competitions" or "squads are paid" as fact. This is a content rule, not a missing URL.
3. **UEFA documents are JavaScript apps.** The URLs open the right article in a browser; a scripted fetch sees
   "Loading application…". If a future test needs to read the rule automatically, use a static UEFA PDF or a
   saved copy, not this URL.
4. **The EFL statement page is also JavaScript-rendered.** The regulation PDF is the authority; the statement is
   only the dated announcement of the change from four to six clubs.
5. **The Premier League handbook is 14.6 MB and season-stamped.** Cite the publications index as the stable
   entry point and the PDF for Rule C.17 itself.
6. **All rows are 2026/27.** Re-check at the season rollover; a rule change is a note change with a new
   `reviewed_at`, not an edit to last season's text.
7. **Two sources are not in English.** The FIGC source is Italian and the RFEF source is Spanish. Each note
   carries the operative clauses in English translation and the document reference (FIGC Communiqué 244/A,
   27 May 2026; RFEF Circular 84, 30 June 2026).
8. **The delay has no provider URL.** It is our measurement, reproduced by `make score-delay`; the note cites
   `_docs/scoping.md` §3 and the command, not a provider page.
9. **La Liga's tiebreak rule is not in LaLiga's general regulation.** That regulation's Article IV.13 only sets
   the points; the tiebreak criteria are Article 10 of the RFEF's 2026/27 competition rules (Circular 84).
   Cite RFEF, not the LaLiga page, for the rule itself.

## How this becomes an M4 task

- `_docs/scoping.md` §8, M4 "done when": every note's sources are listed and checked here.
- `_docs/product-spec.md` `R-F6.1a`: every note's sources are listed with URL, publisher, season and check date.
- `AGENTS.md` next step 4: the notes are written against this table.
- Each note is reviewed like code in the same pull request, and the PR links the row it used.
