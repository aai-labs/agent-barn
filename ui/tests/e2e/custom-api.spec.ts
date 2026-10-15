import { expect, test } from "@playwright/test";

import { CustomApiPage } from "../pages/custom-api-page.po";
import { CustomApiDataSupport } from "../pages/data-support/custom-api-data-support.po";
import { mockAgentAllowedActions } from "../pages/data-support/agent-data-support.po";

test.describe("Custom API integrations", () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test("adds Custom API from the shared integration picker and derives its identifier", async ({ page }) => {
    const data = new CustomApiDataSupport(page);
    const ui = new CustomApiPage(page);
    await data.open({ empty: true });
    await ui.beginEditing();
    await expect(ui.section.getByRole("button", { name: /GitHub/ })).toBeVisible();
    await ui.add.click();
    await ui.field("Connection name").fill("Inventory API");
    await expect(ui.form).toContainText("Identifier: inventory-api");
    await expect(ui.field("Stable identifier")).toHaveCount(0);
    await ui.field("Allowed base URL").fill("https://api.example.com/v1");
    await ui.selectAuth("Bearer token");
    await ui.field("API token").fill("test-token");
    await ui.form.getByRole("switch").click();
    expect(data.requests).toHaveLength(0);
    await ui.confirmApply();
    await expect(ui.form).toHaveCount(0);
    expect(data.requests).toHaveLength(1);
    expect(data.requests[0].body).toMatchObject({ name: "Inventory API", isolated: true, auth: { type: "bearer", token: "test-token" } });
    expect(data.requests[0].body).not.toHaveProperty("slug");
    await expect(ui.section).toContainText("Pending apply");
  });

  test("retains hidden secrets and clears ordinary headers through shared Apply", async ({ page }) => {
    const data = new CustomApiDataSupport(page);
    const ui = new CustomApiPage(page);
    await data.open();
    await ui.beginEditing();
    await ui.expandConnection();
    await expect(ui.field("API token")).toHaveValue("");
    await expect(ui.field("Header value").nth(1)).toHaveValue("");
    await ui.field("Header value").first().fill("");
    await ui.confirmApply();
    await expect(ui.form).toHaveCount(0);
    expect(data.requests[0].body?.auth).toEqual({ type: "api_key", header_name: "X-API-Key" });
    expect(data.requests[0].body?.headers).toEqual([{ name: "Accept", secret: false, value: "" }, { name: "X-Private", secret: true }]);
    expect(data.requests[0].body).not.toHaveProperty("slug");
  });

  test("requires a replacement token when changing the API-key header", async ({ page }) => {
    const data = new CustomApiDataSupport(page);
    const ui = new CustomApiPage(page);
    await data.open();
    await ui.beginEditing();
    await ui.expandConnection();
    await ui.field("Authentication header name").fill("Authorization");
    await expect(ui.field("API token")).toHaveAttribute("required", "");
    await ui.confirmApply();
    expect(data.requests).toHaveLength(0);
    await ui.field("API token").fill("Token replacement");
    await ui.confirmApply();
    await expect(ui.form).toHaveCount(0);
    expect(data.requests[0].body?.auth).toMatchObject({ header_name: "Authorization", token: "Token replacement" });
  });

  test("shared Cancel discards staged changes and removals", async ({ page }) => {
    const data = new CustomApiDataSupport(page);
    const ui = new CustomApiPage(page);
    await data.open();
    await ui.beginEditing();
    await ui.remove.click();
    await ui.add.click();
    await ui.field("Connection name").fill("Unsaved API");
    await ui.cancel.click();
    expect(data.requests).toHaveLength(0);
    await expect(ui.section).toContainText("Inventory API");
    await ui.beginEditing();
    await ui.expandConnection();
    await expect(ui.field("Connection name")).toHaveValue("Inventory API");
  });

  test("running changes use the shared restart confirmation", async ({ page }) => {
    const data = new CustomApiDataSupport(page);
    const ui = new CustomApiPage(page);
    await data.open({ running: true });
    await ui.beginEditing();
    await ui.expandConnection();
    await ui.form.getByRole("switch").click();
    await ui.save.click();
    await expect(ui.dialog).toContainText("Apply changes and restart the Agent?");
    expect(data.requests).toHaveLength(0);
    await ui.dialog.getByRole("button", { name: "Cancel", exact: true }).click();
    await expect(ui.form).toBeVisible();
    await ui.confirmApply();
    await expect(ui.form).toHaveCount(0);
    expect(data.requests[0].url).toMatch(/\/apply$/);
    expect(data.requests[0].body).toMatchObject({ isolated: true, restart: true });
    expect(data.lifecycleRequests).toEqual([]);
  });

  test("stages deletion until shared Apply and restart", async ({ page }) => {
    const data = new CustomApiDataSupport(page);
    const ui = new CustomApiPage(page);
    await data.open({ running: true });
    await ui.beginEditing();
    await ui.remove.click();
    expect(data.requests).toHaveLength(0);
    await ui.confirmApply();
    await expect(ui.section).not.toContainText("Inventory API");
    expect(data.requests[0].method).toBe("DELETE");
    expect(data.requests[0].url).toMatch(/\?restart=true$/);
  });

  test("multiple connections use server bulk Apply with one restart", async ({ page }) => {
    const data = new CustomApiDataSupport(page);
    const ui = new CustomApiPage(page);
    await data.open({ running: true, empty: true });
    await ui.beginEditing();
    for (const name of ["Inventory API", "Reporting API"]) {
      await ui.add.click();
      const form = ui.form.last();
      await form.getByLabel("Connection name", { exact: true }).fill(name);
      await form.getByLabel("Allowed base URL", { exact: true }).fill("https://api.example.com/v1");
    }
    await ui.confirmApply();
    await expect(ui.form).toHaveCount(0);
    expect(data.requests).toHaveLength(1);
    expect(data.lifecycleRequests).toEqual([]);
    expect(data.requests[0].url).toMatch(/\/custom-api-connections\/apply$/);
    expect(data.requests[0].body).toMatchObject({ restart: true, creates: [
      { name: "Inventory API" }, { name: "Reporting API" },
    ] });
  });

  for (const mixed of [false, true]) {
    test(`invalid ${mixed ? "mixed provider and API" : "bulk API"} changes leave the running Agent and drafts intact`, async ({ page }) => {
      const data = new CustomApiDataSupport(page);
      const ui = new CustomApiPage(page);
      await data.open({ running: true, empty: true, fail: true });
      await ui.beginEditing();
      if (mixed) await ui.addGithubCredential();
      for (const name of ["Inventory API", "Inventory/API"]) {
        await ui.add.click();
        await ui.form.last().getByLabel("Connection name", { exact: true }).fill(name);
        await ui.form.last().getByLabel("Allowed base URL", { exact: true }).fill("https://api.example.com/v1");
      }
      await ui.confirmApply();
      await expect(ui.section.getByRole("alert")).toContainText("Invalid Custom API configuration");
      await expect(ui.form).toHaveCount(2);
      expect(data.lifecycleRequests).toEqual([]);
      expect(data.requests[0].url).toMatch(mixed ? /\/preflight$/ : /\/apply$/);
    });
  }

  test("failed saves retain edits and do not restart", async ({ page }) => {
    const data = new CustomApiDataSupport(page);
    const ui = new CustomApiPage(page);
    await data.open({ fail: true });
    await ui.beginEditing();
    await ui.expandConnection();
    await ui.field("Connection name").fill("Updated inventory");
    await ui.confirmApply();
    await expect(ui.section.getByRole("alert")).toContainText("Invalid Custom API configuration");
    await expect(ui.field("Connection name")).toHaveValue("Updated inventory");
    await expect(ui.save).toBeEnabled();
    expect(data.lifecycleRequests).toEqual([]);
  });

  for (const missing of ["agent.update", "agent.secret.manage"]) {
    test(`hides mutations without ${missing}`, async ({ page }) => {
      const ui = new CustomApiPage(page);
      await new CustomApiDataSupport(page).open({ actions: mockAgentAllowedActions.filter((action) => action !== missing) });
      await expect(ui.section).toContainText("Inventory API");
      await expect(ui.edit).toHaveCount(0);
      await expect(ui.add).toHaveCount(0);
    });
  }

  test("managed updates prevent applying changes", async ({ page }) => {
    const ui = new CustomApiPage(page);
    await new CustomApiDataSupport(page).open({ updating: true });
    await ui.beginEditing();
    await ui.remove.click();
    await expect(ui.save).toBeDisabled();
  });

  test("running changes require lifecycle permission", async ({ page }) => {
    const ui = new CustomApiPage(page);
    await new CustomApiDataSupport(page).open({ running: true, actions: mockAgentAllowedActions.filter((action) => action !== "agent.lifecycle.manage") });
    await ui.beginEditing();
    await ui.remove.click();
    await expect(ui.save).toBeDisabled();
  });
});
