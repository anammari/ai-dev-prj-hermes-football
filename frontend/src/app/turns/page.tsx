import Link from "next/link";

import { ErrorPanel } from "@/components/ErrorPanel";
import { Pagination } from "@/components/Pagination";
import { StatusBadge } from "@/components/StatusBadge";
import { adminEnabled, api, showMessages } from "@/lib/api/client";
import type { AgentTurn } from "@/lib/api/client";
import { formatTimestamp, maskMessage } from "@/lib/format";
import { settle } from "@/lib/result";

import { reviewTurnAction } from "./actions";

export const dynamic = "force-dynamic";

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

const REVIEW_STATUSES = ["unreviewed", "correct", "flagged", "wrong"] as const;

function one(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

export default async function TurnsPage({ searchParams }: { searchParams: SearchParams }) {
  const params = await searchParams;
  const limit = Math.min(Number(one(params.limit) ?? 25) || 25, 200);
  const offset = Number(one(params.offset) ?? 0) || 0;
  const groundedRaw = one(params.grounded);
  const grounded = groundedRaw === "true" ? true : groundedRaw === "false" ? false : undefined;
  const reviewStatus = one(params.reviewStatus);
  const reviewResult = one(params.review);
  const reviewError = one(params.reviewError);

  const turns = await settle(api.turns({ limit, offset, grounded, reviewStatus: reviewStatus || undefined }));
  const admin = adminEnabled();
  const show = showMessages();

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Agent turns</h1>
          <p className="lede">
            Every answer the bot gave, with the road it took. Message text is masked by default: the
            review bot is public, and this page is one tunnel away from the internet. Set
            <code> DASHBOARD_SHOW_MESSAGES=true</code> to read it in full.
          </p>
        </div>
      </div>

      {reviewResult === "ok" ? (
        <div className="card" style={{ marginBottom: 14 }}>
          <strong>Review recorded.</strong>
        </div>
      ) : null}
      {reviewError ? (
        <div className="card error" style={{ marginBottom: 14 }} role="alert">
          <strong>Could not record the review.</strong>
          <p className="small muted" style={{ margin: "6px 0 0" }}>
            {reviewError === "forbidden"
              ? "Admin actions are disabled: set API_ADMIN_TOKEN for the dashboard."
              : reviewError === "unauthorized"
                ? "The admin token was refused. Check API_ADMIN_TOKEN."
                : `The API answered ${reviewError}.`}
          </p>
        </div>
      ) : null}

      <form className="controls" method="get">
        <label>
          Route road
          <select name="grounded" defaultValue={groundedRaw ?? ""}>
            <option value="">any</option>
            <option value="true">grounded</option>
            <option value="false">not grounded</option>
          </select>
        </label>
        <label>
          Review
          <select name="reviewStatus" defaultValue={reviewStatus ?? ""}>
            <option value="">any</option>
            {REVIEW_STATUSES.map((status) => (
              <option key={status} value={status}>
                {status}
              </option>
            ))}
          </select>
        </label>
        <button className="button" type="submit">
          Apply
        </button>
        <Link className="button secondary" href="/turns">
          Reset
        </Link>
      </form>

      {turns.ok ? (
        <>
          <table>
            <thead>
              <tr>
                <th>Asked</th>
                <th>Road</th>
                <th>Source</th>
                <th className="num">Latency</th>
                <th>Grounded</th>
                <th>Message</th>
                <th>Answer</th>
                <th>Review</th>
              </tr>
            </thead>
            <tbody>
              {turns.value.data.map((turn: AgentTurn) => (
                <tr key={turn.id}>
                  <td className="small">
                    {formatTimestamp(turn.created_at)}
                    <div className="mono muted" style={{ fontSize: 11 }}>
                      {turn.id.slice(0, 8)}
                    </div>
                  </td>
                  <td>
                    <StatusBadge status={turn.route} label={turn.route ?? "unrecorded"} />
                  </td>
                  <td className="small">
                    {turn.route_source ?? "—"}
                    {turn.route_confidence !== null && turn.route_confidence !== undefined ? (
                      <div className="muted mono" style={{ fontSize: 11 }}>
                        conf {turn.route_confidence.toFixed(2)}
                      </div>
                    ) : null}
                  </td>
                  <td className="num small">
                    {turn.latency_ms !== null && turn.latency_ms !== undefined ? `${turn.latency_ms} ms` : "—"}
                  </td>
                  <td>
                    <StatusBadge status={turn.grounded ? "ok" : "bad"} label={turn.grounded ? "yes" : "no"} />
                  </td>
                  <td style={{ maxWidth: 260 }}>
                    <pre className="message">{maskMessage(turn.user_message, show)}</pre>
                  </td>
                  <td style={{ maxWidth: 300 }}>
                    <pre className="message">{turn.answer}</pre>
                    <div className="small muted">
                      {(turn.tool_calls ?? []).length > 0
                        ? (turn.tool_calls ?? []).map((call) => `${call.name}:${call.status}`).join(" · ")
                        : "no tool calls"}
                    </div>
                  </td>
                  <td style={{ minWidth: 190 }}>
                    <StatusBadge status={turn.review_status} />
                    {admin ? (
                      <form className="review" action={reviewTurnAction} style={{ marginTop: 6 }}>
                        <input type="hidden" name="turnId" value={turn.id} />
                        <select name="reviewStatus" defaultValue={turn.review_status} aria-label="Review status">
                          {REVIEW_STATUSES.map((status) => (
                            <option key={status} value={status}>
                              {status}
                            </option>
                          ))}
                        </select>
                        <input name="note" placeholder="note" maxLength={1000} aria-label="Review note" />
                        <button className="button" type="submit">
                          Save
                        </button>
                      </form>
                    ) : (
                      <div className="small muted">read-only</div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <Pagination
            basePath="/turns"
            limit={limit}
            offset={offset}
            total={turns.value.pagination.total}
            params={{ grounded: groundedRaw, reviewStatus }}
          />
        </>
      ) : (
        <ErrorPanel what="the turn log" message={turns.message} requestId={turns.requestId} />
      )}
    </>
  );
}
