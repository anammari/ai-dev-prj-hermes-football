import { expect, test } from "@playwright/test";

test("the scoreboard draws a series and opens a run", async ({ page }) => {
  await page.goto("/evals");
  await expect(page.getByRole("heading", { name: "Evaluation scoreboard", level: 1 })).toBeVisible();
  await expect(page.locator(".chart svg")).toBeVisible();
  await expect(page.getByText(/target 0\.90 \(dashed\)/)).toBeVisible();

  const firstRun = page.locator("table tbody tr td a").first();
  await firstRun.click();
  await expect(page.getByRole("heading", { name: /Run /, level: 1 })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Per route" })).toBeVisible();
  await expect(page.locator("table").last().locator("tbody tr").first()).toBeVisible();
});
