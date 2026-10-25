import Link from "next/link";

import { ErrorPanel } from "@/components/ErrorPanel";
import { FreshnessBanner } from "@/components/FreshnessBanner";
import { Provenance } from "@/components/Provenance";
import { StatusBadge } from "@/components/StatusBadge";
import { api } from "@/lib/api/client";
import { formatTimestamp } from "@/lib/format";
import { settle } from "@/lib/result";

export const dynamic = "force-dynamic";

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

const STATUSES = [
  "SCHEDULED",
  "TIMED",
  "IN_PLAY",
  "PAUSED",
  "EXTRA_TIME",
  "PENALTY_SHOOTOUT",
  "FINISHED",
  "SUSPENDED",
  "POSTPONED",
  "CANCELLED",
  "AWARDED",
] as const;

function one(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

export default async function FixturesPage({ searchParams }: { searchParams: SearchParams }) {
  const params = await searchParams;
  const competitions = await settle(api.competitions());
  if (!competitions.ok) {
    return (
      <>
        <div className="page-head">
          <h1>Fixtures</h1>
        </div>
        <ErrorPanel what="the competition list" message={competitions.message} requestId={competitions.requestId} />
      </>
    );
  }

  const list = competitions.value.data;
  const code = one(params.code) ?? list[0]?.code ?? "PL";
  const dateFrom = one(params.dateFrom);
  const dateTo = one(params.dateTo);
  const status = one(params.status);
  const teamId = Number(one(params.teamId) ?? "") || undefined;
  const matchId = Number(one(params.match) ?? "") || undefined;

  const [matches, freshness, match] = await Promise.all([
    settle(
      api.matches(code, {
        dateFrom,
        dateTo,
        status: status || undefined,
        limit: 50,
      }),
    ),
    settle(api.freshness()),
    matchId ? settle(api.match(matchId)) : Promise.resolve(null),
  ]);

  const rows = matches.ok ? matches.value.data.filter((row) => (teamId ? row.home_team.id === teamId || row.away_team.id === teamId : true)) : [];

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Fixtures and results</h1>
          <p className="lede">
            Stored fixtures, filtered by date, status or team. The free tier is delayed: a match shown as
            scheduled may already have kicked off, and the timestamp below is the provider&apos;s, not the
            clock.
          </p>
        </div>
      </div>

      {freshness.ok ? <FreshnessBanner freshness={freshness.value} /> : null}

      <div className="chips" style={{ marginBottom: 14 }}>
        {list.map((entry) => (
          <Link
            key={entry.code}
            href={`/fixtures?code=${encodeURIComponent(entry.code)}`}
            aria-current={entry.code === code ? "page" : undefined}
          >
            {entry.code}
          </Link>
        ))}
      </div>

      <form className="controls" method="get">
        <input type="hidden" name="code" value={code} />
        <label>
          From
          <input name="dateFrom" type="date" defaultValue={dateFrom ?? ""} />
        </label>
        <label>
          To
          <input name="dateTo" type="date" defaultValue={dateTo ?? ""} />
        </label>
        <label>
          Status
          <select name="status" defaultValue={status ?? ""}>
            <option value="">any</option>
            {STATUSES.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </label>
        <label>
          Team id
          <input name="teamId" type="number" defaultValue={teamId ?? ""} placeholder="e.g. 57" />
        </label>
        <button className="button" type="submit">
          Apply
        </button>
        <Link className="button secondary" href={`/fixtures?code=${encodeURIComponent(code)}`}>
          Reset
        </Link>
      </form>

      {match?.ok ? (
        <div className="card" style={{ marginBottom: 16 }}>
          <strong>
            {match.value.data.home_team.name} {match.value.data.score?.full_time?.home ?? "–"}
            {" : "}
            {match.value.data.score?.full_time?.away ?? "–"} {match.value.data.away_team.name}
          </strong>
          <p className="small muted" style={{ margin: "6px 0 0" }}>
            {match.value.data.competition.name} · {match.value.data.status} ·{" "}
            {formatTimestamp(match.value.data.utc_date)} · provider last updated{" "}
            {formatTimestamp(match.value.data.last_updated)} · match {match.value.data.id}
          </p>
        </div>
      ) : null}

      {matches.ok ? (
        rows.length === 0 ? (
          <div className="card">
            <strong>No matches for this filter.</strong>
            <p className="small muted" style={{ margin: "6px 0 0" }}>
              If you set a date range, clear it: this volume holds the season&apos;s fixtures, and a
              delayed provider means &quot;today&quot; can be empty.
            </p>
          </div>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Kick-off (UTC)</th>
                <th>Competition</th>
                <th>Home</th>
                <th className="num">Score</th>
                <th>Away</th>
                <th>Status</th>
                <th>Match</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id}>
                  <td className="small">{formatTimestamp(row.utc_date)}</td>
                  <td className="small">{row.competition.name}</td>
                  <td>{row.home_team.name}</td>
                  <td className="num mono">
                    {row.score?.full_time?.home ?? "–"}–{row.score?.full_time?.away ?? "–"}
                  </td>
                  <td>{row.away_team.name}</td>
                  <td>
                    <StatusBadge status={row.status} label={row.status} />
                  </td>
                  <td className="small">
                    <Link
                      href={`/fixtures?code=${encodeURIComponent(code)}&match=${row.id}`}
                      scroll={false}
                    >
                      details
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )
      ) : (
        <ErrorPanel what="the match list" message={matches.message} requestId={matches.requestId} />
      )}
      {matches.ok ? <Provenance meta={matches.value.meta} /> : null}
      {matchId && match && !match.ok ? (
        <ErrorPanel what={`match ${matchId}`} message={match.message} requestId={match.requestId} />
      ) : null}
    </>
  );
}
