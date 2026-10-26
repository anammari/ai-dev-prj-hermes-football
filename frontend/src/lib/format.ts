/**
 * Display helpers. Pure and tested, because a timestamp rendered wrong is a grounding claim rendered
 * wrong: the dashboard exists to say how old the data is.
 */

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** `2026-10-25T04:05:06Z` -> `25 Oct 2026, 04:05 UTC`. Empty input is `unknown`, never "now". */
export function formatTimestamp(value: string | null | undefined): string {
  if (!value) return "unknown";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "unknown";
  const day = String(date.getUTCDate()).padStart(2, "0");
  const month = MONTHS[date.getUTCMonth()] ?? "?";
  const hours = String(date.getUTCHours()).padStart(2, "0");
  const minutes = String(date.getUTCMinutes()).padStart(2, "0");
  return `${day} ${month} ${date.getUTCFullYear()}, ${hours}:${minutes} UTC`;
}

/** `2026-10-25T04:05:06Z` -> `2026-10-25` (the date the data describes, for a table cell). */
export function formatDate(value: string | null | undefined): string {
  if (!value) return "unknown";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "unknown";
  return date.toISOString().slice(0, 10);
}

/** Minutes as a person reads them: `322` -> `5h 22m`, `61` -> `1h 1m`, `9` -> `9m`. */
export function formatAge(minutes: number | null | undefined): string {
  if (minutes === null || minutes === undefined) return "never";
  if (minutes < 1) return "under a minute";
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  if (hours < 24) return rest === 0 ? `${hours}h` : `${hours}h ${rest}m`;
  const days = Math.floor(hours / 24);
  const leftover = hours % 24;
  return leftover === 0 ? `${days}d` : `${days}d ${leftover}h`;
}

/** `0.959969` -> `96.0%`; null stays `—` so an absent metric is not drawn as zero. */
export function formatPercent(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined) return "—";
  return `${(value * 100).toFixed(digits)}%`;
}

/** `17` -> `+17`, `-3` -> `-3`. Goal difference is an integer, not a ratio. */
export function formatGoalDifference(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return value > 0 ? `+${value}` : String(value);
}

/** A ratio with two decimals, or an em dash. */
export function formatScore(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return value.toFixed(2);
}

/**
 * Stored Telegram text is masked unless `DASHBOARD_SHOW_MESSAGES=true`. The review bot is public, and
 * the tunnel is demo-only; the full text stays available in the API and in the owner's terminal.
 */
export function maskMessage(text: string, show: boolean, limit = 90): string {
  if (show) return text;
  const clipped = text.length > limit ? `${text.slice(0, limit).trimEnd()}…` : text;
  return `${clipped} [masked]`;
}

/** A route or status gets a CSS class, not an emoji, so the meaning survives a monochrome screen. */
export function statusTone(status: string | null | undefined): "good" | "warn" | "bad" | "neutral" {
  switch ((status ?? "").toLowerCase()) {
    case "fresh":
    case "ok":
    case "succeeded":
    case "correct":
      return "good";
    case "partial":
    case "stale":
    case "flagged":
      return "warn";
    case "failed":
    case "wrong":
    case "refuse":
      return "bad";
    default:
      return "neutral";
  }
}
