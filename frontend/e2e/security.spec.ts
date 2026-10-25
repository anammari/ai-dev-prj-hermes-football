import { expect, test } from "@playwright/test";

const TOKEN = process.env.API_AGENT_TOKEN ?? "";

test("no token reaches the browser and no request leaves the dashboard origin", async ({ page, baseURL }) => {
  expect(TOKEN.length).toBeGreaterThan(0);

  const external: string[] = [];
  const chunks: string[] = [];
  page.on("request", (request) => {
    const url = request.url();
    if (!url.startsWith(baseURL ?? "")) external.push(url);
    if (url.endsWith(".js")) chunks.push(url);
  });

  await page.goto("/turns");
  await page.waitForLoadState("networkidle");

  // The dashboard is a server-rendered client of the API: the browser talks only to the dashboard.
  expect(external, `requests that left the dashboard origin: ${external.join(", ")}`).toEqual([]);

  // And the token is not in any script the browser downloaded, nor in the HTML.
  for (const url of chunks) {
    const body = await (await page.request.get(url)).text();
    expect(body.includes(TOKEN), `token found in ${url}`).toBe(false);
  }
  expect((await page.content()).includes(TOKEN)).toBe(false);
});
