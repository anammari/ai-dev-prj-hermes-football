import { expect, test } from "@playwright/test";

test("the landing page states freshness before anything else", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Freshness", level: 1 })).toBeVisible();
  const banner = page.locator(".banner");
  await expect(banner).toContainText("Report as of");
  await expect(banner).toContainText("hermes-football ingestion ledger");
  await expect(banner.locator(".badge")).toBeVisible();
  await expect(page.locator("table").first().locator("tbody tr")).not.toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Recent ingestion runs" })).toBeVisible();
});
