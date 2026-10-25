import { defineConfig, devices } from "@playwright/test";

/**
 * The e2e suite runs against the Compose stack, not a dev server: `make e2e` starts the dashboard and
 * points this at `http://frontend:3000`. Locally, `DASHBOARD_URL=http://localhost:3000 pnpm e2e` works
 * once `make up` is running.
 */
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: process.env.DASHBOARD_URL ?? "http://localhost:3000",
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
