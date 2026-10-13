import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { expect, test } from "@playwright/test";

const expectedVersion =
  process.env.E2E_EXPECTED_VERSION ??
  readFileSync(resolve(__dirname, "../../VERSION"), "utf8").trim();

test("server info dialog shows the build version", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: new RegExp(`^v${expectedVersion}`) }).click();

  const dialog = page.getByRole("dialog", { name: "About InfraKitchen" });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByText(`v${expectedVersion}`, { exact: true })).toBeVisible();
});
