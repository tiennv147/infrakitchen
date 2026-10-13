import { expect, test as setup } from "@playwright/test";

setup("log in as guest super user", async ({ page }) => {
  await page.goto("/login");
  await expect(page.getByText("Welcome to InfraKitchen")).toBeVisible();

  await page.getByRole("button", { name: "Log in as a Guest" }).click();
  await page.getByText("Guest Login (Super User)").click();

  await expect(
    page.getByRole("heading", { level: 1, name: /^(Welcome|Dashboard)$/ }),
  ).toBeVisible();
  await page.context().storageState({ path: "playwright/.auth/guest-super.json" });
});
