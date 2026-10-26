import { ErrorPanel } from "@/components/ErrorPanel";
import { FreshnessBanner } from "@/components/FreshnessBanner";
import { Metric } from "@/components/Metric";
import { StatusBadge } from "@/components/StatusBadge";
import { api } from "@/lib/api/client";
import { formatAge, formatTimestamp } from "@/lib/format";
import { settle } from "@/lib/result";

export const dynamic = "force-dynamic";

const COMPETITION_LIMIT = 40;

export default async function FreshnessPage() {
  const [freshness, runs] = await Promise.all([
    settle(api.freshness()),
    settle(api.ingestRuns({ limit: 8 })),
  ]);

  if (!freshness.ok) {
    return (
      <div className="page-head">
        <h1>Freshness</h1>
      </div>
    );
  }

  const report = freshness.value;
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Freshness</h1>
          <p className="lede">
            How old the stored data is, per competition, from the ingestion ledger. A competition we
            cannot vouch for says <code>unknown</code>; it is never painted green.
          </p>
        </div>
      </div>

      <FreshnessBanner freshness={freshness.value} />

      <div className="grid">
        <Metric
          label="Overall"
          value={report.overall_status}
          note={`${report.competitions.length} competitions known`}
        />
        <Metric label="Oldest refresh" value={formatAge(report.max_age_minutes)} note="across competitions" />
        <Metric label="Next scheduled run" value={formatTimestamp(report.next_scheduled_run_at)} note="utc" />
      </div>

      <h2>Competitions</h2>
      <table>
        <thead>
          <tr>
            <th>Code</th>
            <th>Competition</th>
            <th>Status</th>
            <th>Last run</th>
            <th>Last success</th>
            <th className="num">Age</th>
            <th className="num">Matches</th>
            <th className="num">Table rows</th>
            <th className="num">Teams</th>
          </tr>
        </thead>
        <tbody>
          {report.competitions.slice(0, COMPETITION_LIMIT).map((row: (typeof report.competitions)[number]) => (
            <tr key={row.code}>
              <td className="mono">{row.code}</td>
              <td>{row.name ?? "—"}</td>
              <td>
                <StatusBadge status={row.status} />
              </td>
              <td>
                <StatusBadge status={row.last_status} label={row.last_status} />
              </td>
              <td className="small">{formatTimestamp(row.last_success_at)}</td>
              <td className="num">{formatAge(row.age_minutes)}</td>
              <td className="num">{row.rows?.matches ?? 0}</td>
              <td className="num">{row.rows?.standings ?? 0}</td>
              <td className="num">{row.rows?.teams ?? 0}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <h2>Recent ingestion runs</h2>
      {runs.ok ? (
        <table>
          <thead>
            <tr>
              <th>Started</th>
              <th>Status</th>
              <th>Trigger</th>
              <th className="num">Duration</th>
              <th className="num">Calls</th>
              <th>Scope</th>
              <th>Errors</th>
            </tr>
          </thead>
          <tbody>
            {runs.value.data.map((run) => (
              <tr key={run.id}>
                <td className="small">{formatTimestamp(run.started_at)}</td>
                <td>
                  <StatusBadge status={run.status} />
                </td>
                <td>{run.trigger}</td>
                <td className="num">{run.duration_seconds ? `${Math.round(run.duration_seconds)}s` : "—"}</td>
                <td className="num">{run.calls_used ?? "—"}</td>
                <td className="small">
                  {(run.competitions ?? []).length === 0 ? (
                    <em>no scope (measurement)</em>
                  ) : (
                    (run.competitions ?? []).join(", ")
                  )}
                </td>
                <td className="small">
                  {(run.errors ?? []).length === 0 ? (
                    <span className="muted">none</span>
                  ) : (
                    <ul style={{ margin: 0, paddingLeft: 16 }}>
                      {(run.errors ?? []).slice(0, 3).map((error, index) => (
                        <li key={index}>{error.message}</li>
                      ))}
                    </ul>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <ErrorPanel what="the ingestion ledger" message={runs.message} requestId={runs.requestId} />
      )}
    </>
  );
}
