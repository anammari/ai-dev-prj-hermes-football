import { StatusBadge } from "@/components/StatusBadge";
import type { Freshness } from "@/lib/api/client";
import { formatAge, formatTimestamp } from "@/lib/format";

/**
 * Rule 2, on screen: the page says how old the data is. Freshness is computed from the ingestion
 * ledger rather than served with a provider envelope, so the timestamp shown is the report's `as_of`
 * and the source is named for what it is - our own ledger - not for the provider it describes.
 */
export function FreshnessBanner({ freshness }: { freshness: Freshness }) {
  return (
    <div className="banner">
      <StatusBadge status={freshness.overall_status} />
      <span>
        Report as of <strong>{formatTimestamp(freshness.as_of)}</strong>, source:{" "}
        <strong>hermes-football ingestion ledger</strong>
      </span>
      <span className="muted small">
        oldest refresh {formatAge(freshness.max_age_minutes)} · next run{" "}
        {formatTimestamp(freshness.next_scheduled_run_at)}
      </span>
      <span className="spacer" />
      <span className="muted small">{freshness.competitions.length} competitions</span>
    </div>
  );
}
