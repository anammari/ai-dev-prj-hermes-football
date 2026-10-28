import { expect, test } from "@playwright/test";

test("a stored table renders with its provenance and switches competition", async ({ page }) => {
  // The competition the seed world stores a table for. The default chip is whichever competition this
  // deployment lists first, and a fresh deployment may not have ingested that one yet.
  await page.goto("/standings?code=PL");
  await expect(page.getByRole("heading", { name: "Standings", level: 1 })).toBeVisible();
  await expect(page.locator("table tbody tr").first()).toBeVisible();
  await expect(page.getByText(/As of .*source football-data\.org/)).toBeVisible();

  const firstChip = page.locator(".chips a").first();
  const code = (await firstChip.textContent())?.trim();
  await firstChip.click();
  await expect(page).toHaveURL(new RegExp(`code=${code}`));
});
