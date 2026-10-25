/**
 * A failed call, shown as a failure. The request id is the point: it is what an operator needs to find
 * the same request in the API log, and the contract promises it on every error.
 */
export function ErrorPanel({ what, message, requestId }: { what: string; message: string; requestId: string | null }) {
  return (
    <div className="card error" role="alert">
      <strong>Could not load {what}.</strong>
      <p className="small muted" style={{ margin: "6px 0 0" }}>
        {message}
      </p>
      {requestId ? (
        <p className="small muted mono" style={{ margin: "4px 0 0" }}>
          request id {requestId}
        </p>
      ) : null}
    </div>
  );
}
