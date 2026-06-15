import { expect, test } from "@playwright/test";

import {
  mockAgentTemplate,
  mockTemplates,
} from "../pages/data-support/agent-data-support.po";
import { DataSupport } from "../pages/data-support/data-support.po";

test.describe("Settings · Templates", () => {
  test.describe.configure({ mode: "serial" });
  let dataSupport: DataSupport;

  test.use({ storageState: { cookies: [], origins: [] } });

  test.beforeEach(async ({ page }) => {
    dataSupport = new DataSupport(page);

    await dataSupport.auth.interceptRefreshRequest();
    await dataSupport.users.interceptGetUserContextRequest();
    await dataSupport.agents.interceptGetTemplatesRequest();

    await page.goto("/dashboard/settings");
    await page.getByRole("button", { name: "Templates", exact: true }).click();
  });

  test("lists templates with slug, version, and source badges", async ({ page }) => {
    await expect(page.getByText("General Purpose", { exact: true })).toBeVisible();
    await expect(page.getByText("· general-purpose@v1")).toBeVisible();
    // Badge spans only — the source filter <option> also says "Pre-defined".
    await expect(page.locator('span:text-is("Pre-defined")')).toHaveCount(2);
    await expect(page.getByText("My Custom", { exact: true })).toBeVisible();
  });

  test("search filters the list", async ({ page }) => {
    await page.getByLabel("Search templates").fill("scrum");

    await expect(page.getByText("Scrum Master", { exact: true })).toBeVisible();
    await expect(page.getByText("General Purpose", { exact: true })).not.toBeVisible();
  });

  test("source filter narrows to custom templates", async ({ page }) => {
    await page.getByLabel("Filter by source").selectOption("custom");

    await expect(page.getByText("My Custom", { exact: true })).toBeVisible();
    await expect(page.getByText("Scrum Master", { exact: true })).not.toBeVisible();
  });

  test("clicking a template opens a read-only preview with the version shown", async ({ page }) => {
    await dataSupport.agents.interceptGetTemplateRequest({ slug: "scrum-master" });

    await page.getByText("Scrum Master", { exact: true }).click();

    await expect(page.getByRole("heading", { name: "Scrum Master" })).toBeVisible();
    await expect(page.getByText("Version v1")).toBeVisible();
    const content = page.getByLabel("SOUL.md content");
    await expect(content).toBeVisible();
    await expect(content).toHaveAttribute("readonly", "");
    await expect(content).toHaveValue(/\{\{ agent_display_name \}\}/);
    // Version is displayed, never editable.
    await expect(page.getByLabel("Template name")).toHaveCount(0);
  });

  test("edit template enables fields and save publishes a new version", async ({ page }) => {
    await dataSupport.agents.interceptGetTemplateRequest({ slug: "my-custom" });
    await dataSupport.agents.interceptUpdateTemplateRequest({ slug: "my-custom" });

    await page.getByText("My Custom", { exact: true }).click();
    await page.getByRole("button", { name: "Edit template" }).click();

    const content = page.getByLabel("SOUL.md content");
    await expect(content).not.toHaveAttribute("readonly", "");
    await content.fill("# Soul v2");

    const patchPromise = page.waitForRequest(
      (req) => req.url().includes("/api/v1/templates/my-custom") && req.method() === "PATCH",
    );
    await page.getByRole("button", { name: "Save", exact: true }).click();
    const patchRequest = await patchPromise;
    const body = patchRequest.postDataJSON() as Record<string, unknown>;
    expect(body.soul_md).toBe("# Soul v2");
    expect(body.template_name).toBe("My Custom");

    await expect(page.getByText("Saved as v2")).toBeVisible();
  });

  test("new template posts template_name and md content", async ({ page }) => {
    await dataSupport.agents.interceptCreateTemplateRequest({
      body: { ...mockAgentTemplate, template_slug: "support-helper", template_name: "Support Helper" },
    });

    await page.getByRole("button", { name: /new template/i }).click();
    await page.getByLabel("Template name").fill("Support Helper");
    await expect(page.getByText("Slug:")).toContainText("support-helper");
    await page.getByLabel("SOUL.md content").fill("# A fresh soul");

    const createPromise = page.waitForRequest(
      (req) => req.url().endsWith("/api/v1/templates") && req.method() === "POST",
    );
    await page.getByRole("button", { name: "Create template" }).click();
    const createRequest = await createPromise;
    const body = createRequest.postDataJSON() as Record<string, unknown>;
    expect(body.template_name).toBe("Support Helper");
    expect(body.soul_md).toBe("# A fresh soul");
  });

  test("conflict on create surfaces the backend error", async ({ page }) => {
    await dataSupport.agents.interceptCreateTemplateRequest({
      status: 409,
      detail: `A template with slug ${mockTemplates[2].template_slug} already exists`,
    });

    await page.getByRole("button", { name: /new template/i }).click();
    await page.getByLabel("Template name").fill("My Custom");
    await page.getByRole("button", { name: "Create template" }).click();

    await expect(page.getByText(/already exists/)).toBeVisible();
  });
});
