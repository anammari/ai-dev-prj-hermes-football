import Link from "next/link";

/**
 * Links, not buttons: paging is a URL, so a page can be bookmarked and the back button works. Every
 * other filter is carried through, or page two silently forgets the filter that page one had.
 */
export function Pagination({
  basePath,
  limit,
  offset,
  total,
  params,
}: {
  basePath: string;
  limit: number;
  offset: number;
  total: number;
  params: Record<string, string | undefined>;
}) {
  const href = (nextOffset: number) => {
    const search = new URLSearchParams();
    for (const [key, value] of Object.entries(params)) {
      if (value) search.set(key, value);
    }
    search.set("limit", String(limit));
    search.set("offset", String(nextOffset));
    return `${basePath}?${search.toString()}`;
  };
  const from = total === 0 ? 0 : offset + 1;
  const to = Math.min(offset + limit, total);
  return (
    <div className="pager small muted">
      <span>
        {from}–{to} of {total}
      </span>
      {offset > 0 ? (
        <Link href={href(Math.max(0, offset - limit))} className="button secondary">
          Previous
        </Link>
      ) : null}
      {offset + limit < total ? (
        <Link href={href(offset + limit)} className="button secondary">
          Next
        </Link>
      ) : null}
    </div>
  );
}
