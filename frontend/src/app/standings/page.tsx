import Link from "next/link";

import { ErrorPanel } from "@/components/ErrorPanel";
import { FreshnessBanner } from "@/components/FreshnessBanner";
import { Provenance } from "@/components/Provenance";
import { api } from "@/lib/api/client";
import { formatDate, formatGoalDifference } from "@/lib/format";
import { settle } from "@/lib/result";

export const dynamic = "force-dynamic";

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

function one(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

/**
 * The table explorer. Competition and snapshot are query parameters, so a view can be linked to - the
 * contract makes the snapshot a first-class question ("where were they in November?") and the page
 * exposes it rather than hiding it behind a click.
 */
export default async function StandingsPage({ searchParams }: { searchParams: SearchParams }) {
  const params = await searchParams;
  const competitions = await settle(api.competitions());
  if (!competitions.ok) {
    return (
      <>
        <div className="page-head">
          <h1>Standings</h1>
        </div>
        <ErrorPanel
          what="the competition list"
          message={competitions.message}
          requestId={competitions.requestId}
        />
      </>
    );
  }

  const list = competitions.value.data;
  const code = one(params.code) ?? list[0]?.code ?? "PL";
  const season = Number(one(params.season) ?? "") || undefined;
  const snapshot = one(params.snapshot);
  const matchday = Number(one(params.matchday) ?? "") || undefined;

  const [table, freshness] = await Promise.all([
    settle(api.standings(code, { season, snapshot, matchday })),
    settle(api.freshness()),
  ]);
  const competition = list.find((entry) => entry.code === code);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Standings</h1>
          <p className="lede">
            The most recent stored table, or the table as it stood on a date. Only the total table is
            served; home and away splits stay in the database.
          </p>
        </div>
      </div>

      {freshness.ok ? <FreshnessBanner freshness={freshness.value} /> : null}

      <div className="chips" style={{ marginBottom: 14 }}>
        {list.map((entry) => (
          <Link
            key={entry.code}
            href={`/standings?code=${encodeURIComponent(entry.code)}`}
            aria-current={entry.code === code ? "page" : undefined}
          >
            {entry.code}
          </Link>
        ))}
      </div>

      <form className="controls" method="get">
        <input type="hidden" name="code" value={code} />
        <label>
          Season
          <input name="season" type="number" defaultValue={season ?? competition?.current_season ?? ""} />
        </label>
        <label>
          As it stood on
          <input name="snapshot" type="date" defaultValue={snapshot ?? ""} />
        </label>
        <label>
          Matchday
          <input name="matchday" type="number" min={1} defaultValue={matchday ?? ""} />
        </label>
        <button className="button" type="submit">
          Apply
        </button>
        <Link className="button secondary" href={`/standings?code=${encodeURIComponent(code)}`}>
          Reset
        </Link>
      </form>

      {table.ok ? (
        <>
          <p className="small muted">
            {competition?.name ?? code} · season {table.value.data.season} ·{" "}
            {table.value.data.matchday ? `matchday ${table.value.data.matchday} · ` : ""}
            snapshot {formatDate(table.value.data.updated_at)} · type {table.value.data.type}
            {table.value.data.group ? ` · group ${table.value.data.group}` : ""}
          </p>
          <table>
            <thead>
              <tr>
                <th className="num">#</th>
                <th>Team</th>
                <th className="num">P</th>
                <th className="num">W</th>
                <th className="num">D</th>
                <th className="num">L</th>
                <th className="num">GF</th>
                <th className="num">GA</th>
                <th className="num">GD</th>
                <th className="num">Pts</th>
                <th>Form</th>
              </tr>
            </thead>
            <tbody>
              {table.value.data.table.map((row) => (
                <tr key={row.team.id}>
                  <td className="num">{row.position}</td>
                  <td>
                    <Link href={`/fixtures?code=${encodeURIComponent(code)}&teamId=${row.team.id}`}>
                      {row.team.name}
                    </Link>
                  </td>
                  <td className="num">{row.played}</td>
                  <td className="num">{row.won}</td>
                  <td className="num">{row.drawn}</td>
                  <td className="num">{row.lost}</td>
                  <td className="num">{row.goals_for}</td>
                  <td className="num">{row.goals_against}</td>
                  <td className="num">{formatGoalDifference(row.goal_difference)}</td>
                  <td className="num">
                    <strong>{row.points}</strong>
                  </td>
                  <td className="mono small">{row.form ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <Provenance meta={table.value.meta} />
        </>
      ) : (
        <ErrorPanel what={`the ${code} table`} message={table.message} requestId={table.requestId} />
      )}
    </>
  );
}
