import { expect, test } from "@playwright/test";

import { CustomApiPage } from "../pages/custom-api-page.po";
import { CustomApiDataSupport } from "../pages/data-support/custom-api-data-support.po";
import { mockAgentAllowedActions } from "../pages/data-support/agent-data-support.po";

test.describe("Custom API connections", () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test("creates an isolated connection with a stable identifier", async ({
    page,
  }) => {
    const data = new CustomApiDataSupport(page);
    const ui = new CustomApiPage(page);
    await data.open({ empty: true });
    await ui.add.click();
    await ui.field("Connection name").fill("Inventory API");
    await ui.field("Stable identifier").fill("inventory");
    await ui.field("Allowed base URL").fill("https://api.example.com/v1");
    await ui.selectAuth("Bearer token");
    await ui.field("API token").fill("test-token");
    await ui.field("Isolate credentials").click();
    await ui.save.click();
    await expect(ui.form).toHaveCount(0);
    expect(data.requests).toHaveLength(1);
    expect(data.requests[0].body).toMatchObject({
      slug: "inventory",
      isolated: true,
      auth: { type: "bearer", token: "test-token" },
    });
    await expect(ui.section).toContainText("Pending apply");
  });

  test("keeps saved secrets hidden and retains them while clearing an ordinary header", async ({
    page,
  }) => {
    const data = new CustomApiDataSupport(page);
    const ui = new CustomApiPage(page);
    await data.open();
    await ui.edit.click();
    await expect(ui.field("Stable identifier")).toBeDisabled();
    await expect(ui.field("API token")).toHaveValue("");
    await expect(ui.field("Header value").nth(1)).toHaveValue("");
    await ui.field("Header value").first().fill("");
    await ui.save.click();
    await expect(ui.form).toHaveCount(0);
    expect(data.requests[0].method).toBe("PATCH");
    expect(data.requests[0].body?.auth).toEqual({
      type: "api_key",
      header_name: "X-API-Key",
    });
    expect(data.requests[0].body?.headers).toEqual([
      { name: "Accept", secret: false, value: "" },
      { name: "X-Private", secret: true },
    ]);
    expect(data.requests[0].body).not.toHaveProperty("slug");
  });

  test("requires replacement credentials after changing an API-key header", async ({
    page,
  }) => {
    const data = new CustomApiDataSupport(page);
    const ui = new CustomApiPage(page);
    await data.open();
    await ui.edit.click();
    await ui.field("Authentication header name").fill("Authorization");
    await ui.save.click();
    expect(data.requests).toHaveLength(0);
    await expect(ui.field("API token")).toHaveAttribute("required", "");
    await ui.field("API token").fill("Token replacement");
    await ui.save.click();
    await expect(ui.form).toHaveCount(0);
    expect(data.requests[0].body?.auth).toMatchObject({
      header_name: "Authorization",
      token: "Token replacement",
    });
  });

  test("confirms running changes and supports cancel before restarting", async ({
    page,
  }) => {
    const data = new CustomApiDataSupport(page);
    const ui = new CustomApiPage(page);
    await data.open({ running: true });
    await expect(ui.add).toBeEnabled();
    await expect(ui.remove).toBeEnabled();
    await ui.edit.click();
    await ui.field("Isolate credentials").click();
    await ui.save.click();
    await expect(ui.dialog).toContainText(
      "Apply Custom API changes and restart?",
    );
    expect(data.requests).toHaveLength(0);
    await ui.dialog
      .getByRole("button", { name: "Cancel", exact: true })
      .click();
    await expect(ui.form).toBeVisible();
    await ui.save.click();
    await ui.dialog
      .getByRole("button", { name: "Apply & Restart", exact: true })
      .click();
    await expect(ui.form).toHaveCount(0);
    expect(data.requests).toHaveLength(1);
    expect(data.requests[0].url).toMatch(/\/apply$/);
    expect(data.requests[0].body).toMatchObject({
      isolated: true,
      restart: true,
    });
  });

  test("creates a running connection after explicit restart confirmation", async ({
    page,
  }) => {
    const data = new CustomApiDataSupport(page);
    const ui = new CustomApiPage(page);
    await data.open({ running: true, empty: true });
    await ui.add.click();
    await ui.field("Connection name").fill("Inventory API");
    await ui.field("Stable identifier").fill("inventory");
    await ui.field("Allowed base URL").fill("https://api.example.com:8443/v1");
    await ui.save.click();
    expect(data.requests).toHaveLength(0);
    await ui.dialog
      .getByRole("button", { name: "Apply & Restart", exact: true })
      .click();
    await expect(ui.form).toHaveCount(0);
    expect(data.requests[0].body).toMatchObject({
      restart: true,
      base_url: "https://api.example.com:8443/v1",
    });
    expect(data.requests[0].url).toMatch(/custom-api-connections$/);
  });

  test("deletes a running connection after explicit restart confirmation", async ({
    page,
  }) => {
    const data = new CustomApiDataSupport(page);
    const ui = new CustomApiPage(page);
    await data.open({ running: true });
    await ui.remove.click();
    expect(data.requests).toHaveLength(0);
    await ui.dialog
      .getByRole("button", { name: "Delete & Restart", exact: true })
      .click();
    await expect(ui.section).toContainText(
      "No Custom API connections configured.",
    );
    expect(data.requests[0].url).toMatch(/\?restart=true$/);
  });

  test("disables mutations during a managed update", async ({ page }) => {
    const ui = new CustomApiPage(page);
    await new CustomApiDataSupport(page).open({ updating: true });
    await expect(ui.edit).toBeDisabled();
    await expect(ui.remove).toBeDisabled();
    await expect(ui.add).toBeDisabled();
  });

  test("keeps edits available after a failed save", async ({ page }) => {
    const data = new CustomApiDataSupport(page);
    const ui = new CustomApiPage(page);
    await data.open({ fail: true });
    await ui.edit.click();
    await ui.field("Connection name").fill("Updated inventory");
    await ui.save.click();
    await expect(ui.section.getByRole("alert")).toContainText(
      "Invalid Custom API configuration",
    );
    await expect(ui.field("Connection name")).toHaveValue("Updated inventory");
    await expect(ui.save).toBeEnabled();
  });

  test("deletes only after confirmation", async ({ page }) => {
    const data = new CustomApiDataSupport(page);
    const ui = new CustomApiPage(page);
    await data.open();
    await ui.remove.click();
    expect(data.requests).toHaveLength(0);
    await ui.dialog
      .getByRole("button", { name: "Delete connection", exact: true })
      .click();
    await expect(ui.section).toContainText(
      "No Custom API connections configured.",
    );
    expect(data.requests[0].method).toBe("DELETE");
  });

  for (const missing of ["agent.update", "agent.secret.manage"]) {
    test(`hides mutation controls without ${missing}`, async ({ page }) => {
      const ui = new CustomApiPage(page);
      await new CustomApiDataSupport(page).open({
        actions: mockAgentAllowedActions.filter((action) => action !== missing),
      });
      await expect(ui.section).toContainText("Inventory API");
      await expect(ui.add).toHaveCount(0);
      await expect(ui.edit).toHaveCount(0);
      await expect(ui.remove).toHaveCount(0);
    });
  }

  test("disables running editing without restart permission", async ({
    page,
  }) => {
    const ui = new CustomApiPage(page);
    await new CustomApiDataSupport(page).open({
      running: true,
      actions: mockAgentAllowedActions.filter(
        (action) => action !== "agent.lifecycle.manage",
      ),
    });
    await expect(ui.edit).toBeDisabled();
  });
});
