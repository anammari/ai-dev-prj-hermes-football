"use client";

export default function ErrorPage({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <>
      <div className="page-head">
        <h1>Something failed</h1>
      </div>
      <div className="card error" role="alert">
        <strong>The dashboard could not render this page.</strong>
        <p className="small muted" style={{ margin: "6px 0 12px" }}>
          {error.message}
          {error.digest ? ` (digest ${error.digest})` : ""}
        </p>
        <button className="button" onClick={reset} type="button">
          Try again
        </button>
      </div>
    </>
  );
}
