import { expect, test } from "@playwright/test";

const listPages = [
  { path: "/projects", heading: "Projects" },
  { path: "/templates", heading: "Templates" },
  { path: "/source_code_versions", heading: "Template Versions" },
  { path: "/resources", heading: "Resources" },
  { path: "/integrations", heading: "Integrations" },
  { path: "/source_codes", heading: "Code Repositories" },
  { path: "/storages", heading: "Storages" },
  { path: "/secrets", heading: "Secrets" },
  { path: "/executors", heading: "Executors" },
  { path: "/batch_operations", heading: "Batch Operations" },
  { path: "/tasks", heading: "Tasks" },
  { path: "/workers", heading: "Workers" },
  { path: "/roles", heading: "Roles" },
  { path: "/audit_logs", heading: "Audit Logs" },
];

test("dashboard loads after login", async ({ page }) => {
  await page.goto("/");
  await expect(
    page.getByRole("heading", { level: 1, name: /^(Welcome|Dashboard)$/ }).first(),
  ).toBeVisible();
});

for (const { path, heading } of listPages) {
  test(`${path} renders without page errors`, async ({ page }) => {
    const pageErrors: Error[] = [];
    page.on("pageerror", (error) => pageErrors.push(error));

    await page.goto(path);
    await expect(
      page.getByRole("heading", { level: 1, name: heading, exact: true }),
    ).toBeVisible();
    expect(pageErrors).toEqual([]);
  });
}
