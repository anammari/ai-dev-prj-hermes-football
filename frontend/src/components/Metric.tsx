export function Metric({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="card metric">
      <span className="label">{label}</span>
      <span className="value">{value}</span>
      {note ? <span className="small muted">{note}</span> : null}
    </div>
  );
}
