import { expect, test } from "@playwright/test";

import UserContext from "../fixtures/user-context.json";
import { AgentSizesSettingsPage } from "../pages/agent-sizes-settings-page.po";
import { AgentSizeDataSupport, mockSize, STANDARD_SIZE_ID } from "../pages/data-support/agent-size-data-support.po";
import { DataSupport } from "../pages/data-support/data-support.po";

const MIB = 1024 ** 2;
const GIB = 1024 ** 3;
const LARGE_ID = "22222222-2222-4222-8222-000000000001";

test.describe("Platform Agent sizes (platform_admin)", () => {
  let sizesPage: AgentSizesSettingsPage;
  let sizes: AgentSizeDataSupport;

  test.use({ storageState: { cookies: [], origins: [] } });

  test.beforeEach(async ({ page }) => {
    sizesPage = new AgentSizesSettingsPage(page);
    sizes = new AgentSizeDataSupport(page);
    const data = new DataSupport(page);
    await data.auth.interceptRefreshRequest();
    await data.users.interceptGetUserContextRequest({ userContext: { ...UserContext, is_platform_admin: true } });
    await data.users.interceptGetOrganizationsRequest();
  });

  test("lists the catalog with Standard as the default, in vCPU and memory", async ({ page }) => {
    await sizes.intercept();

    await sizesPage.goto();

    await expect(sizesPage.heading()).toBeVisible();
    await expect(sizesPage.row("Standard")).toContainText("Default");
    await expect(sizesPage.row("Standard")).toContainText("0.5 vCPU");
    await expect(sizesPage.row("Standard")).toContainText("request 0.05 vCPU");
    await expect(sizesPage.row("Standard")).toContainText("1 GiB");
    await expect(sizesPage.row("Standard")).toContainText("request 320 MiB");
    // The default is always enabled, so its switch can't be turned off.
    await expect(sizesPage.enabledSwitch("Standard")).toBeDisabled();
    await expect(page.getByRole("complementary").getByRole("link", { name: "Agent sizes" })).toHaveAttribute(
      "aria-current",
      "page",
    );
  });

  test("adds a size, sending millicores and bytes", async () => {
    const { writes } = await sizes.intercept();
    await sizesPage.goto();

    await sizesPage.addSize();
    await sizesPage.fill({
      Name: "Large",
      "CPU request (vCPU)": "0.5",
      "CPU limit (vCPU)": "2",
      "Memory request (MiB)": "2048",
      "Memory limit (MiB)": "4096",
    });
    await sizesPage.submit();

    await expect(sizesPage.dialog()).toBeHidden();
    expect(writes).toEqual([
      {
        method: "POST",
        body: {
          name: "Large",
          cpu_request_millicores: 500,
          cpu_limit_millicores: 2000,
          memory_request_bytes: 2 * GIB,
          memory_limit_bytes: 4 * GIB,
        },
      },
    ]);
    await expect(sizesPage.row("Large")).toContainText("2 vCPU");
    await expect(sizesPage.row("Large")).toContainText("4 GiB");
  });

  test("refuses a request above its limit before anything is sent", async () => {
    const { writes } = await sizes.intercept();
    await sizesPage.goto();

    await sizesPage.addSize();
    await sizesPage.fill({
      Name: "Lopsided",
      "CPU request (vCPU)": "2",
      "CPU limit (vCPU)": "1",
      "Memory request (MiB)": "512",
      "Memory limit (MiB)": "abc",
    });
    await sizesPage.submit();

    await expect(sizesPage.dialog()).toContainText("The request can't be more than the limit.");
    await expect(sizesPage.dialog()).toContainText("Enter whole MiB above 0");
    expect(writes).toEqual([]);
  });

  test("shows the API's refusal in the dialog and keeps the edit", async () => {
    await sizes.intercept({ failWith: { status: 409, detail: "A size named 'Standard' already exists" } });
    await sizesPage.goto();

    await sizesPage.addSize();
    await sizesPage.fill({
      Name: "Standard",
      "CPU request (vCPU)": "0.1",
      "CPU limit (vCPU)": "1",
      "Memory request (MiB)": "512",
      "Memory limit (MiB)": "1024",
    });
    await sizesPage.submit();

    await expect(sizesPage.dialog().getByTestId("agent-size-error")).toContainText("already exists");
    await expect(sizesPage.field("Name")).toHaveValue("Standard");
  });

  test("edits a size, starting from what is saved", async () => {
    const { writes } = await sizes.intercept();
    await sizesPage.goto();

    await sizesPage.openActions("Standard");
    await sizesPage.action("Edit").click();
    await expect(sizesPage.field("Memory request (MiB)")).toHaveValue("320");
    await expect(sizesPage.field("CPU request (vCPU)")).toHaveValue("0.05");
    await sizesPage.fill({ "Memory limit (MiB)": "1536" });
    await sizesPage.submit();

    await expect(sizesPage.dialog()).toBeHidden();
    expect(writes).toEqual([
      {
        method: "PATCH",
        id: STANDARD_SIZE_ID,
        body: {
          name: "Standard",
          cpu_request_millicores: 50,
          cpu_limit_millicores: 500,
          memory_request_bytes: 320 * MIB,
          memory_limit_bytes: 1536 * MIB,
        },
      },
    ]);
  });

  test("makes another size the default after confirming, which moves the badge", async () => {
    const { writes } = await sizes.intercept({
      sizes: [
        mockSize({ following_agent_count: 3 }),
        mockSize({ id: LARGE_ID, name: "Large", is_default: false, sort_order: 1 }),
      ],
    });
    await sizesPage.goto();

    await sizesPage.openActions("Large");
    await sizesPage.action("Make default").click();
    await expect(sizesPage.confirmDialog()).toContainText("3 agents that follow Standard move to Large");
    await sizesPage.confirm("Make default").click();

    await expect(sizesPage.row("Large")).toContainText("Default");
    await expect(sizesPage.row("Standard")).not.toContainText("Default");
    expect(writes).toEqual([{ method: "PATCH", id: LARGE_ID, body: { is_default: true } }]);
    await expect(sizesPage.enabledSwitch("Standard")).toBeEnabled();
  });

  test("disables a size, and a disabled size can't be made the default", async () => {
    const { writes } = await sizes.intercept({
      sizes: [mockSize(), mockSize({ id: LARGE_ID, name: "Large", is_default: false })],
    });
    await sizesPage.goto();

    await sizesPage.enabledSwitch("Large").click();
    await expect(sizesPage.enabledSwitch("Large")).toHaveAttribute("aria-checked", "false");
    expect(writes).toEqual([{ method: "PATCH", id: LARGE_ID, body: { enabled: false } }]);

    await sizesPage.openActions("Large");
    await expect(sizesPage.action("Make default")).toHaveAttribute("data-disabled", "");
  });

  test("asks before disabling a size agents are on, since they stay on it", async () => {
    const { writes } = await sizes.intercept({
      sizes: [mockSize(), mockSize({ id: LARGE_ID, name: "Large", is_default: false, agent_count: 2 })],
    });
    await sizesPage.goto();

    await sizesPage.enabledSwitch("Large").click();
    await expect(sizesPage.confirmDialog()).toContainText("2 agents on Large stay on it");
    expect(writes).toEqual([]);
    await sizesPage.confirm("Disable size").click();

    await expect(sizesPage.enabledSwitch("Large")).toHaveAttribute("aria-checked", "false");
    expect(writes).toEqual([{ method: "PATCH", id: LARGE_ID, body: { enabled: false } }]);
  });

  test("deletes a size after confirming, and never offers to delete the default", async () => {
    const { writes } = await sizes.intercept({
      sizes: [mockSize(), mockSize({ id: LARGE_ID, name: "Large", is_default: false })],
    });
    await sizesPage.goto();

    await sizesPage.openActions("Standard");
    await expect(sizesPage.action("Delete")).toHaveCount(0);
    await sizesPage.action("Edit").press("Escape");

    await sizesPage.openActions("Large");
    await sizesPage.action("Delete").click();
    await sizesPage.confirmDelete().click();

    await expect(sizesPage.row("Large")).toHaveCount(0);
    expect(writes).toEqual([{ method: "DELETE", id: LARGE_ID, body: undefined }]);
  });

  test("fits a phone without scrolling the page sideways", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await sizes.intercept();

    await sizesPage.goto();
    await expect(sizesPage.row("Standard")).toBeVisible();

    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow).toBe(0);
  });
});

test.describe("Platform Agent sizes (non platform_admin)", () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test("is not shown to someone without Platform Privilege", async ({ page }) => {
    const data = new DataSupport(page);
    await data.auth.interceptRefreshRequest();
    await data.users.interceptGetUserContextRequest({ userContext: { ...UserContext, is_platform_admin: false } });
    await data.users.interceptGetOrganizationsRequest();
    const { writes } = await new AgentSizeDataSupport(page).intercept();

    await new AgentSizesSettingsPage(page).goto();

    await expect(page.getByRole("table", { name: "Agent sizes" })).toHaveCount(0);
    expect(writes).toEqual([]);
  });
});
