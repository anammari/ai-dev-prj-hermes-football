import { statusTone } from "@/lib/format";

export function StatusBadge({ status, label }: { status: string | null | undefined; label?: string }) {
  const text = label ?? status ?? "unknown";
  return <span className={`badge ${statusTone(status)}`}>{text}</span>;
}
