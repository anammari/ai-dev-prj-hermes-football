import type { EvalRun } from "@/lib/api/client";
import { formatTimestamp } from "@/lib/format";

/**
 * Routing macro-F1 over time, one line per golden set.
 *
 * Two rules make the picture honest. Runs are grouped by `set_name` **and** the set's hash: a score
 * computed on a different sample - or on a later revision of the same-named sample - is a different
 * series, not a point on the same trend, and the backfilled M4 holdout must not be drawn as if it
 * continued into the golden set. A run with no routing metric is skipped rather than plotted at zero.
 * The 0.90 target is a line across the plot, not a decoration.
 */

export const TARGET_MACRO_F1 = 0.9;

const WIDTH = 760;
const HEIGHT = 240;
const PAD = { top: 16, right: 18, bottom: 28, left: 44 };

const COLOURS = ["#14532d", "#1d4ed8", "#b45309", "#7c3aed", "#be123c"];

export type Point = { x: number; y: number; run: EvalRun };
export type Series = { name: string; colour: string; points: Point[] };

export function macroF1(run: EvalRun): number | null {
  const metrics = run.metrics as { routing?: { macro_f1?: unknown } } | null;
  const value = metrics?.routing?.macro_f1;
  return typeof value === "number" ? value : null;
}

export function seriesKey(run: EvalRun): string {
  return `${run.set_name} · ${run.golden_set_sha256.slice(0, 8)}`;
}

export function seriesFrom(runs: EvalRun[]): Series[] {
  const grouped = new Map<string, EvalRun[]>();
  for (const run of runs) {
    if (macroF1(run) === null) continue;
    const key = seriesKey(run);
    const bucket = grouped.get(key) ?? [];
    bucket.push(run);
    grouped.set(key, bucket);
  }
  return [...grouped.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([name, bucket], index) => ({
      name,
      colour: COLOURS[index % COLOURS.length] ?? "#14532d",
      points: [...bucket]
        .sort((a, b) => a.started_at.localeCompare(b.started_at))
        .map((run) => ({ x: Date.parse(run.started_at), y: macroF1(run) ?? 0, run })),
    }));
}

export function EvalChart({ runs }: { runs: EvalRun[] }) {
  const series = seriesFrom(runs);
  if (series.length === 0) {
    return (
      <div className="card">
        <strong>No scored runs yet.</strong>
        <p className="small muted" style={{ margin: "6px 0 0" }}>
          Run <code>make eval</code> once; the run appears here with its routing macro-F1 and its gate.
        </p>
      </div>
    );
  }

  const times = series.flatMap((line) => line.points.map((point) => point.x));
  const minX = Math.min(...times);
  const maxX = Math.max(...times);
  const span = maxX - minX || 1;
  const plotWidth = WIDTH - PAD.left - PAD.right;
  const plotHeight = HEIGHT - PAD.top - PAD.bottom;
  const sx = (x: number) => PAD.left + ((x - minX) / span) * plotWidth;
  const sy = (y: number) => PAD.top + (1 - y) * plotHeight;
  const gridlines = [1, 0.9, 0.75, 0.5];

  return (
    <div className="chart">
      <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} role="img" aria-label="Routing macro-F1 by evaluation run">
        {gridlines.map((value) => (
          <g key={value}>
            <line
              x1={PAD.left}
              x2={WIDTH - PAD.right}
              y1={sy(value)}
              y2={sy(value)}
              stroke={value === TARGET_MACRO_F1 ? "#b45309" : "#e2e5ea"}
              strokeDasharray={value === TARGET_MACRO_F1 ? "5 4" : undefined}
            />
            <text x={PAD.left - 8} y={sy(value) + 4} textAnchor="end" fontSize="11" fill="#5c6270">
              {value.toFixed(2)}
            </text>
          </g>
        ))}
        {series.map((line) => (
          <g key={line.name}>
            <polyline
              fill="none"
              stroke={line.colour}
              strokeWidth="2.2"
              points={line.points.map((point) => `${sx(point.x)},${sy(point.y)}`).join(" ")}
            />
            {line.points.map((point) => (
              <circle
                key={point.run.id}
                cx={sx(point.x)}
                cy={sy(point.y)}
                r="4"
                fill={point.run.passed ? line.colour : "#ffffff"}
                stroke={line.colour}
                strokeWidth="2"
              >
                <title>
                  {`${point.run.set_name} · ${formatTimestamp(point.run.started_at)} · macro-F1 ${point.y.toFixed(3)}`}
                </title>
              </circle>
            ))}
          </g>
        ))}
        <text x={PAD.left} y={HEIGHT - 8} fontSize="11" fill="#5c6270">
          {formatTimestamp(new Date(minX).toISOString())}
        </text>
        <text x={WIDTH - PAD.right} y={HEIGHT - 8} fontSize="11" fill="#5c6270" textAnchor="end">
          {formatTimestamp(new Date(maxX).toISOString())}
        </text>
      </svg>
      <div className="legend">
        {series.map((line) => (
          <span key={line.name}>
            <span className="swatch" style={{ background: line.colour }} />
            {line.name}
          </span>
        ))}
        <span>
          <span className="swatch" style={{ background: "#b45309" }} />
          target {TARGET_MACRO_F1.toFixed(2)} (dashed)
        </span>
        <span>hollow point = run failed its gate</span>
      </div>
    </div>
  );
}
