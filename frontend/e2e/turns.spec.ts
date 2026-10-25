import { expect, test } from "@playwright/test";

test("the audit log masks message text by default", async ({ page }) => {
  await page.goto("/turns");
  await expect(page.getByRole("heading", { name: "Agent turns", level: 1 })).toBeVisible();
  const rows = page.locator("table tbody tr");
  await expect(rows.first()).toBeVisible();
  await expect(rows.first()).toContainText("[masked]");
  await expect(page.getByText("read-only").or(page.getByRole("button", { name: "Save" })).first()).toBeVisible();
});
