import Link from "next/link";

import { EvalChart } from "@/components/EvalChart";
import { ErrorPanel } from "@/components/ErrorPanel";
import { Metric } from "@/components/Metric";
import { StatusBadge } from "@/components/StatusBadge";
import { api } from "@/lib/api/client";
import { formatPercent, formatScore, formatTimestamp } from "@/lib/format";
import { metricNumber } from "@/lib/evals";
import { settle } from "@/lib/result";

export const dynamic = "force-dynamic";

export default async function EvalsPage() {
  const runs = await settle(api.evalRuns({ limit: 100 }));
  if (!runs.ok) {
    return (
      <>
        <div className="page-head">
          <h1>Evaluation scoreboard</h1>
        </div>
        <ErrorPanel what="the eval runs" message={runs.message} requestId={runs.requestId} />
      </>
    );
  }

  const list = [...runs.value.data].sort((a, b) => b.started_at.localeCompare(a.started_at));
  const latest = list[0];
  const live = list.filter((run) => run.source === "live");
  const sets = new Set(list.map((run) => run.set_name));

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Evaluation scoreboard</h1>
          <p className="lede">
            Golden-question runs, newest first. Routing macro-F1 is drawn per set because a score on a
            different sample is not a continuation of the same trend. The dashed line is the 0.90 target
            the M4 gate was measured against.
          </p>
        </div>
      </div>

      <div className="grid" style={{ marginBottom: 16 }}>
        <Metric
          label="Latest macro-F1"
          value={latest ? formatScore(metricNumber(latest, ["routing", "macro_f1"])) : "—"}
          note={latest ? `prompt v${latest.prompt_version} · ${latest.set_name}` : "no runs yet"}
        />
        <Metric
          label="Latest gate"
          value={latest ? (latest.passed ? "passed" : "failed") : "—"}
          note={latest && latest.failure_reasons.length > 0 ? latest.failure_reasons[0] : "no failures recorded"}
        />
        <Metric label="Runs" value={String(list.length)} note={`${live.length} live · ${list.length - live.length} backfilled`} />
        <Metric label="Sets" value={String(sets.size)} note={[...sets].join(", ")} />
      </div>

      <EvalChart runs={list} />

      <h2>Runs</h2>
      <table>
        <thead>
          <tr>
            <th>Started</th>
            <th>Set</th>
            <th>Prompt</th>
            <th>Model</th>
            <th className="num">Macro-F1</th>
            <th className="num">Accuracy</th>
            <th className="num">Recall@k</th>
            <th className="num">Facts</th>
            <th>Gate</th>
            <th>Source</th>
          </tr>
        </thead>
        <tbody>
          {list.map((run) => (
            <tr key={run.id}>
              <td className="small">
                <Link href={`/evals/${run.id}`}>{formatTimestamp(run.started_at)}</Link>
              </td>
              <td className="small mono">{run.set_name}</td>
              <td className="small">v{run.prompt_version}</td>
              <td className="small">{run.model}</td>
              <td className="num">{formatScore(metricNumber(run, ["routing", "macro_f1"]))}</td>
              <td className="num">{formatPercent(metricNumber(run, ["routing", "accuracy"]))}</td>
              <td className="num">{formatPercent(metricNumber(run, ["retrieval", "recall_at_k"]))}</td>
              <td className="num">{formatPercent(metricNumber(run, ["answers", "fact_coverage"]))}</td>
              <td>
                <StatusBadge status={run.passed ? "ok" : "failed"} label={run.passed ? "passed" : "failed"} />
              </td>
              <td className="small">
                {run.source}
                {run.source === "backfill" ? <span className="muted"> (routing only)</span> : null}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="small muted">
        A run with no retrieval row was not measured for retrieval: the M4 holdout protocol scored routing
        only, and those runs are imported as the baseline. Absent is not zero.
      </p>
    </>
  );
}
