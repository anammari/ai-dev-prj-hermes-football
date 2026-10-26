import type { Schemas } from "@/lib/api/client";
import { formatTimestamp } from "@/lib/format";

/**
 * The provenance line for a response that carries an envelope: what the data describes, and who said
 * so. Freshness itself has no envelope (it is derived from the ledger), which is why this is a
 * separate component rather than part of the banner.
 */
export function Provenance({ meta }: { meta: Schemas["ResponseMeta"] }) {
  return (
    <p className="small muted">
      As of <strong>{formatTimestamp(meta.data_as_of)}</strong>, source <strong>{meta.source}</strong>
      {meta.upstream_delay_minutes !== null && meta.upstream_delay_minutes !== undefined
        ? ` · upstream delay ${meta.upstream_delay_minutes} min`
        : ""}{" "}
      · generated {formatTimestamp(meta.generated_at)}
    </p>
  );
}
