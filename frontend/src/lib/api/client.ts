import "server-only";

import type { components, operations } from "./schema";

/**
 * The dashboard's only door to the API.
 *
 * Two rules shape this module. First, it runs on the server: the `server-only` import makes the build
 * fail if a client component ever imports it, so `API_AGENT_TOKEN` and `API_ADMIN_TOKEN` cannot reach
 * the browser bundle. Second, every function names an operation from the generated contract types, so
 * a renamed path, parameter or field is a type error rather than a runtime 404.
 *
 * The types come from `openapi.yaml` (`pnpm gen:api`, checked by `pnpm check:api`). There is no second
 * hand-written description of the API here.
 */

export type Schemas = components["schemas"];

type Ok<Op extends keyof operations> = operations[Op] extends {
  responses: { 200: { content: { "application/json": infer Body } } };
}
  ? Body
  : never;

type Query = Record<string, string | number | boolean | undefined | null>;

const BASE_URL = (process.env.BACKEND_BASE_URL ?? "http://localhost:8000").replace(/\/+$/, "");
const AGENT_TOKEN = process.env.API_AGENT_TOKEN ?? "";
const ADMIN_TOKEN = process.env.API_ADMIN_TOKEN ?? "";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly requestId: string | null;
  readonly details: unknown;

  constructor(status: number, code: string, message: string, requestId: string | null, details: unknown = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.requestId = requestId;
    this.details = details;
  }
}

export class ApiUnavailable extends Error {
  constructor(message: string, options?: { cause?: unknown }) {
    super(message, options);
    this.name = "ApiUnavailable";
  }
}

export function adminEnabled(): boolean {
  return ADMIN_TOKEN.length > 0;
}

/** Whether the turns page may render message text. Off by default: the review bot is public. */
export function showMessages(): boolean {
  return (process.env.DASHBOARD_SHOW_MESSAGES ?? "false").toLowerCase() === "true";
}

async function call<Body>(
  path: string,
  options: { query?: Query; method?: "GET" | "PATCH"; body?: unknown; admin?: boolean } = {},
): Promise<Body> {
  const url = new URL(`${BASE_URL}${path}`);
  for (const [key, value] of Object.entries(options.query ?? {})) {
    if (value !== undefined && value !== null && value !== "") {
      url.searchParams.set(key, String(value));
    }
  }

  const token = options.admin ? ADMIN_TOKEN : AGENT_TOKEN;
  if (!token) {
    throw new ApiUnavailable(
      options.admin
        ? "Admin actions are disabled: API_ADMIN_TOKEN is not set for the dashboard."
        : "API_AGENT_TOKEN is not set for the dashboard, so the API would refuse every request.",
    );
  }

  let response: Response;
  try {
    response = await fetch(url.toString(), {
      method: options.method ?? "GET",
      headers: {
        Authorization: `Bearer ${token}`,
        Accept: "application/json",
        ...(options.body === undefined ? {} : { "Content-Type": "application/json" }),
      },
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      // Freshness is the product; a cached dashboard would quote data as older or newer than it is.
      cache: "no-store",
    });
  } catch (error) {
    throw new ApiUnavailable(`The API at ${BASE_URL} did not answer.`, { cause: error });
  }

  const text = await response.text();
  const payload: unknown = text ? safeJson(text) : null;

  if (!response.ok) {
    const envelope = errorEnvelope(payload);
    throw new ApiError(
      response.status,
      envelope?.code ?? `http_${response.status}`,
      envelope?.message ?? `The API answered ${response.status}.`,
      envelope?.requestId ?? response.headers.get("x-request-id"),
      envelope?.details ?? null,
    );
  }
  return payload as Body;
}

type ErrorEnvelope = { code: string; message: string; requestId: string | null; details: unknown };

function errorEnvelope(payload: unknown): ErrorEnvelope | null {
  if (typeof payload !== "object" || payload === null || !("error" in payload)) return null;
  const error = (payload as { error?: Record<string, unknown> }).error;
  if (typeof error !== "object" || error === null) return null;
  const code = typeof error.code === "string" ? error.code : "unknown_error";
  const message = typeof error.message === "string" ? error.message : "The API returned an error.";
  const requestId = typeof error.request_id === "string" ? error.request_id : null;
  return { code, message, requestId, details: error.details ?? null };
}

function safeJson(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

// ------------------------------------------------------------------------------------------------
// Operations. One function per endpoint the dashboard uses, named after the contract's operationId.
// ------------------------------------------------------------------------------------------------

export const api = {
  health: () => call<Ok<"getHealth">>("/health"),

  freshness: () => call<Ok<"getFreshness">>("/meta/freshness"),

  ingestRuns: (query: { limit?: number } = {}) =>
    call<Ok<"listIngestRuns">>("/meta/ingest-runs", { query: { limit: query.limit ?? 8 } }),

  competitions: () => call<Ok<"listCompetitions">>("/competitions"),

  standings: (code: string, query: { season?: number; snapshot?: string; matchday?: number } = {}) =>
    call<Ok<"getStandings">>(`/competitions/${encodeURIComponent(code)}/standings`, { query }),

  matches: (
    code: string,
    query: { season?: number; dateFrom?: string; dateTo?: string; status?: string; limit?: number } = {},
  ) => call<Ok<"listCompetitionMatches">>(`/competitions/${encodeURIComponent(code)}/matches`, { query }),

  match: (id: number) => call<Ok<"getMatch">>(`/matches/${id}`),

  turns: (query: { limit?: number; offset?: number; grounded?: boolean; reviewStatus?: string } = {}) =>
    call<Ok<"listAgentTurns">>("/agent/turns", { query }),

  evalRuns: (query: { limit?: number; setName?: string; passed?: boolean } = {}) =>
    call<Ok<"listEvalRuns">>("/evals/runs", { query }),

  evalRun: (id: string) => call<Ok<"getEvalRun">>(`/evals/runs/${encodeURIComponent(id)}`),

  reviewTurn: (id: string, body: { reviewStatus: string; note?: string }) =>
    call<Ok<"reviewAgentTurn">>(`/admin/agent-turns/${encodeURIComponent(id)}/review`, {
      method: "PATCH",
      body,
      admin: true,
    }),
};

export type Api = typeof api;
// `/meta/freshness` is the one factual operation whose 200 body is the report itself, not an
// envelope: there is no upstream timestamp to echo, because the report is computed from the ledger.
export type Freshness = Schemas["FreshnessReport"];
export type AgentTurns = Ok<"listAgentTurns">;
export type EvalRuns = Ok<"listEvalRuns">;
export type EvalRunDetail = Ok<"getEvalRun">;
export type Standings = Ok<"getStandings">;
export type Matches = Ok<"listCompetitionMatches">;
export type Competitions = Ok<"listCompetitions">;
export type IngestRuns = Ok<"listIngestRuns">;
export type AgentTurn = Schemas["AgentTurn"];
export type EvalRun = Schemas["EvalRun"];
export type EvalResult = Schemas["EvalResult"];
