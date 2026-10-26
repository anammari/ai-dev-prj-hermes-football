import { expect, test } from "@playwright/test";

test("fixtures answer with either a table or an explicit empty state", async ({ page }) => {
  await page.goto("/fixtures");
  await expect(page.getByRole("heading", { name: "Fixtures and results", level: 1 })).toBeVisible();
  const table = page.locator("table");
  const empty = page.getByText("No matches for this filter.");
  await expect(table.or(empty)).toBeVisible();
  if (await table.isVisible()) {
    await expect(table.locator("tbody tr").first()).toBeVisible();
  }
});
