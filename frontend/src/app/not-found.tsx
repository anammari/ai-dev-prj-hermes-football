import Link from "next/link";

export default function NotFound() {
  return (
    <>
      <div className="page-head">
        <h1>Not found</h1>
      </div>
      <div className="card">
        <p style={{ marginTop: 0 }}>
          The API has no such resource: a run id that does not exist, a competition with no table, or a
          page that was never built.
        </p>
        <Link className="button" href="/">
          Back to freshness
        </Link>
      </div>
    </>
  );
}
