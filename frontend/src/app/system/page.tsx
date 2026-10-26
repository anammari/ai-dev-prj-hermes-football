import { ErrorPanel } from "@/components/ErrorPanel";
import { Metric } from "@/components/Metric";
import { StatusBadge } from "@/components/StatusBadge";
import { api } from "@/lib/api/client";
import { settle } from "@/lib/result";

export const dynamic = "force-dynamic";

function uptime(seconds: number): string {
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  if (hours >= 24) return `${Math.floor(hours / 24)}d ${hours % 24}h`;
  return hours > 0 ? `${hours}h ${minutes}m` : `${minutes}m`;
}

export default async function SystemPage() {
  const health = await settle(api.health());
  return (
    <>
      <div className="page-head">
        <div>
          <h1>System</h1>
          <p className="lede">
            The API&apos;s own liveness probe. It is the one unauthenticated operation in the contract, so
            this page works even when a token is misconfigured — which is exactly when you need it.
          </p>
        </div>
      </div>
      {health.ok ? (
        <>
          <div className="grid">
            <Metric label="API" value={health.value.status} note={`version ${health.value.version}`} />
            <Metric
              label="Database"
              value={health.value.db.status}
              note={`schema ${health.value.db.schema_revision}`}
            />
            <Metric label="Uptime" value={uptime(health.value.uptime_seconds ?? 0)} note="this process" />
          </div>
          <h2>Contract</h2>
          <div className="card small">
            <p style={{ marginTop: 0 }}>
              The API serves <code>openapi.yaml</code> verbatim at <code>/openapi.yaml</code> and renders it at{" "}
              <code>/docs</code>. The generated FastAPI document is deliberately not published: one
              contract, one source of truth.
            </p>
            <p style={{ marginBottom: 0 }}>
              <a href="http://localhost:8000/docs" rel="noreferrer">
                Open Swagger UI
              </a>{" "}
              (backend on <code>:8000</code>).
            </p>
          </div>
        </>
      ) : (
        <ErrorPanel what="the health probe" message={health.message} requestId={health.requestId} />
      )}
      <h2>Degraded states this page can show</h2>
      <table>
        <thead>
          <tr>
            <th>State</th>
            <th>Means</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>
              <StatusBadge status="ok" />
            </td>
            <td>The probe reached the process and the database.</td>
          </tr>
          <tr>
            <td>
              <StatusBadge status="degraded" />
            </td>
            <td>The process is up but the database is unreachable; the API still answers, with no data.</td>
          </tr>
          <tr>
            <td>
              <StatusBadge status="unknown" />
            </td>
            <td>The dashboard could not reach the API at all — check `docker compose ps`.</td>
          </tr>
        </tbody>
      </table>
    </>
  );
}
