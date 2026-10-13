import { expect, test } from "@playwright/test";

test("create and delete a project", async ({ page }) => {
  const name = `e2e-project-${Date.now()}`;

  await page.goto("/projects/create");
  await expect(page.getByRole("heading", { name: "Create Project" })).toBeVisible();
  await page.getByLabel("Project name").fill(name);
  await page.getByLabel("Project description").fill("Created by the Playwright E2E suite");
  await page.getByRole("button", { name: "Save" }).click();

  await expect(page).toHaveURL(/\/projects\/[0-9a-f-]{36}/);
  await expect(page.getByRole("heading", { name: "Project Details" })).toBeVisible();
  await expect(page.getByText(name).first()).toBeVisible();

  await page.getByRole("tab", { name: "Settings" }).click();

  // A project must be disabled before it can be deleted.
  for (const action of ["Disable", "Delete"]) {
    await page.getByRole("button", { name: action, exact: true }).click();
    const dialog = page.getByRole("dialog").filter({ hasText: "Confirmation" });
    await expect(dialog).toContainText(`Are you sure you want to ${action.toLowerCase()} ${name}`);
    await dialog.getByRole("button").filter({ hasText: new RegExp(`^${action}$`) }).click();
    await expect(dialog).toBeHidden();
  }

  await expect(page).toHaveURL(/\/projects$/);
  await expect(page.getByText(name)).toHaveCount(0);
});
