import { afterEach, describe, expect, it, vi } from "vitest";

const ENV = {
  BACKEND_BASE_URL: "http://api.test",
  API_AGENT_TOKEN: "agent-token",
  API_ADMIN_TOKEN: "admin-token",
  DASHBOARD_SHOW_MESSAGES: "false",
};

async function loadClient(overrides: Record<string, string | undefined> = {}) {
  vi.resetModules();
  for (const [key, value] of Object.entries({ ...ENV, ...overrides })) {
    if (value === undefined) delete process.env[key];
    else process.env[key] = value;
  }
  return import("./client");
}

afterEach(() => {
  vi.unstubAllGlobals();
});

function respond(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

describe("the API client", () => {
  it("sends the agent bearer token, drops empty query values, and never caches", async () => {
    const calls: { url: string; init: RequestInit }[] = [];
    vi.stubGlobal("fetch", async (url: string, init: RequestInit) => {
      calls.push({ url, init });
      return respond({ data: [], meta: {}, pagination: { limit: 10, offset: 0, total: 0, has_more: false } });
    });
    const { api } = await loadClient();
    await api.evalRuns({ limit: 10, setName: undefined });
    expect(calls).toHaveLength(1);
    expect(calls[0]?.url).toBe("http://api.test/evals/runs?limit=10");
    expect((calls[0]?.init.headers as Record<string, string>).Authorization).toBe("Bearer agent-token");
    expect(calls[0]?.init.cache).toBe("no-store");
  });

  it("uses the admin token only for the review operation", async () => {
    const headers: string[] = [];
    vi.stubGlobal("fetch", async (_url: string, init: RequestInit) => {
      headers.push((init.headers as Record<string, string>).Authorization ?? "");
      return respond({ data: { id: "t1" }, meta: {} });
    });
    const { api } = await loadClient();
    await api.turns({});
    await api.reviewTurn("t1", { reviewStatus: "correct" });
    expect(headers).toEqual(["Bearer agent-token", "Bearer admin-token"]);
  });

  it("maps a contract error to an ApiError with its code and request id", async () => {
    vi.stubGlobal("fetch", async () =>
      respond(
        { error: { code: "not_found", message: "No evaluation run.", request_id: "req-1", details: { runId: "x" } } },
        404,
      ),
    );
    const { api, ApiError } = await loadClient();
    const failure = await api.evalRun("missing").catch((error: unknown) => error);
    expect(failure).toBeInstanceOf(ApiError);
    expect((failure as InstanceType<typeof ApiError>).status).toBe(404);
    expect((failure as InstanceType<typeof ApiError>).code).toBe("not_found");
    expect((failure as InstanceType<typeof ApiError>).requestId).toBe("req-1");
  });

  it("reports an unreachable API as ApiUnavailable, not as an empty page", async () => {
    vi.stubGlobal("fetch", async () => {
      throw new Error("ECONNREFUSED");
    });
    const { api, ApiUnavailable } = await loadClient();
    await expect(api.freshness()).rejects.toBeInstanceOf(ApiUnavailable);
  });

  it("refuses to call the API with no token at all", async () => {
    vi.stubGlobal("fetch", async () => respond({}));
    const { api, ApiUnavailable } = await loadClient({ API_AGENT_TOKEN: undefined });
    await expect(api.freshness()).rejects.toBeInstanceOf(ApiUnavailable);
  });

  it("knows whether admin actions and message text are enabled", async () => {
    const { adminEnabled, showMessages } = await loadClient();
    expect(adminEnabled()).toBe(true);
    expect(showMessages()).toBe(false);
    const { adminEnabled: off } = await loadClient({ API_ADMIN_TOKEN: undefined });
    expect(off()).toBe(false);
  });
});
