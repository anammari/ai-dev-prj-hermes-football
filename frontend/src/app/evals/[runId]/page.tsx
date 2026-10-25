import Link from "next/link";
import { notFound } from "next/navigation";

import { ErrorPanel } from "@/components/ErrorPanel";
import { Metric } from "@/components/Metric";
import { StatusBadge } from "@/components/StatusBadge";
import { api } from "@/lib/api/client";
import { at, gateList, metricNumber, metricText, perRoute } from "@/lib/evals";
import { formatPercent, formatScore, formatTimestamp } from "@/lib/format";
import { settle } from "@/lib/result";

export const dynamic = "force-dynamic";

type Params = Promise<{ runId: string }>;

export default async function EvalRunPage({ params }: { params: Params }) {
  const { runId } = await params;
  const detail = await settle(api.evalRun(runId));
  if (!detail.ok) {
    if (detail.message.includes("not_found")) notFound();
    return (
      <>
        <div className="page-head">
          <h1>Evaluation run</h1>
        </div>
        <ErrorPanel what="the run" message={detail.message} requestId={detail.requestId} />
      </>
    );
  }

  const run = detail.value.data.run;
  const results = detail.value.data.results;
  const routes = perRoute(run);
  const misses = results.filter((result) => result.scores.routing_correct === false);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Run {run.id.slice(0, 8)}</h1>
          <p className="lede">
            {run.set_name} · prompt v{run.prompt_version} · {run.model} · commit{" "}
            <span className="mono">{run.git_commit.slice(0, 7)}</span> · {run.source}
          </p>
        </div>
        <Link className="button secondary" href="/evals">
          All runs
        </Link>
      </div>

      <div className="banner">
        <StatusBadge status={run.passed ? "ok" : "failed"} label={run.passed ? "gate passed" : "gate failed"} />
        <span>
          Started {formatTimestamp(run.started_at)} · finished {formatTimestamp(run.finished_at)}
        </span>
        <span className="spacer" />
        <span className="muted small">set hash {run.golden_set_sha256.slice(0, 12)}</span>
      </div>

      {run.failure_reasons.length > 0 ? (
        <div className="card error" style={{ marginBottom: 16 }}>
          <strong>Why this run failed</strong>
          <ul className="small" style={{ margin: "6px 0 0", paddingLeft: 18 }}>
            {run.failure_reasons.map((reason) => (
              <li key={reason}>{reason}</li>
            ))}
          </ul>
        </div>
      ) : null}

      <div className="grid">
        <Metric label="Macro-F1" value={formatScore(metricNumber(run, ["routing", "macro_f1"]))} note="four routes, unweighted" />
        <Metric label="Accuracy" value={formatPercent(metricNumber(run, ["routing", "accuracy"]))} note="route match" />
        <Metric
          label="Recall@k"
          value={formatPercent(metricNumber(run, ["retrieval", "recall_at_k"]))}
          note="expected notes found"
        />
        <Metric
          label="Fact coverage"
          value={formatPercent(metricNumber(run, ["answers", "fact_coverage"]))}
          note="required terms present"
        />
        <Metric
          label="Citations"
          value={formatPercent(metricNumber(run, ["answers", "citation_coverage"]))}
          note="answers carrying a source"
        />
        <Metric label="Errors" value={String(metricNumber(run, ["routing", "errors"]) ?? 0)} note="failed calls, not retried" />
      </div>

      <h2>Per route</h2>
      {routes.length === 0 ? (
        <p className="small muted">This run did not record a per-route table.</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Route</th>
              <th className="num">Support</th>
              <th className="num">Precision</th>
              <th className="num">Recall</th>
              <th className="num">F1</th>
            </tr>
          </thead>
          <tbody>
            {routes.map((entry) => (
              <tr key={entry.route}>
                <td>{entry.route}</td>
                <td className="num">{entry.support ?? "—"}</td>
                <td className="num">{formatScore(entry.precision)}</td>
                <td className="num">{formatScore(entry.recall)}</td>
                <td className="num">{formatScore(entry.f1)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <h2>Gates</h2>
      <div className="card small">
        <p style={{ marginTop: 0 }}>
          Adversarial refused <strong>{metricText(run, ["gates", "adversarial_refused"]) ?? "—"}</strong> ·
          fabricated <strong>{metricText(run, ["gates", "fabricated_refused"]) ?? "—"}</strong> · unsupported{" "}
          <strong>{metricText(run, ["gates", "unsupported_refused"]) ?? "—"}</strong> with reason{" "}
          <strong>{metricText(run, ["gates", "unsupported_with_reason"]) ?? "—"}</strong>
        </p>
        <p style={{ marginBottom: 0 }}>
          False refusals:{" "}
          {gateList(run, "false_refusals").length === 0 ? (
            <span className="muted">none</span>
          ) : (
            <span className="mono">{gateList(run, "false_refusals").join(", ")}</span>
          )}{" "}
          · database→notes:{" "}
          {gateList(run, "database_to_notes").length === 0 ? (
            <span className="muted">none</span>
          ) : (
            <span className="mono">{gateList(run, "database_to_notes").join(", ")}</span>
          )}
        </p>
      </div>

      <h2>Questions ({results.length})</h2>
      <p className="small muted">
        {misses.length} routing miss{misses.length === 1 ? "" : "es"}. A miss here is what a macro-F1 drop
        is made of.
      </p>
      <table>
        <thead>
          <tr>
            <th>Question</th>
            <th>Class</th>
            <th>Expected</th>
            <th>Actual</th>
            <th>Tool</th>
            <th className="num">Recall</th>
            <th className="num">Facts</th>
            <th>Cited</th>
          </tr>
        </thead>
        <tbody>
          {results.map((result) => {
            const correct = result.scores.routing_correct !== false;
            return (
              <tr key={result.id}>
                <td className="small mono">{result.question_id}</td>
                <td className="small">{result.class}</td>
                <td className="small">
                  {result.expected_route}
                  {result.expected_tool ? <span className="muted">/{result.expected_tool}</span> : null}
                </td>
                <td className="small">
                  <StatusBadge
                    status={correct ? "ok" : "bad"}
                    label={result.route ?? (result.error ? "error" : "none")}
                  />
                </td>
                <td className="small">{result.tool ?? "—"}</td>
                <td className="num small">
                  {typeof result.scores.recall === "number" ? formatPercent(result.scores.recall) : "—"}
                </td>
                <td className="num small">
                  {typeof result.scores.fact_coverage === "number"
                    ? formatPercent(result.scores.fact_coverage)
                    : "—"}
                </td>
                <td className="small">{result.scores.cited === false ? "no" : "yes"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="small muted">
        Run as of {formatTimestamp(detail.value.meta.data_as_of)} · request{" "}
        <span className="mono">{detail.value.meta.request_id}</span> · thresholds{" "}
        {String((at(run, ["runtime", "thresholds"]) as Record<string, number> | undefined)?.macro_f1 ?? 0.9)}
      </p>
    </>
  );
}
