import { test, expect } from "@playwright/test";

test("@PROJ-123 customer can cancel an unpaid order", async ({ page }) => {
  await page.goto("/orders/1");
  await page.getByRole("button", { name: "Cancel" }).click();
  await expect(page.getByText("Cancelled")).toBeVisible();
});
