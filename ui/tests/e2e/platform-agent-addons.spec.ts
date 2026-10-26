import { expect, test } from "@playwright/test";

import UserContext from "../fixtures/user-context.json";
import { PlatformAgentAddonsPage } from "../pages/agent-addons-page.po";
import { AppNavigation } from "../pages/app-navigation.po";
import { AgentAddonDataSupport, mockPlatformAgentAddon } from "../pages/data-support/agent-addon-data-support.po";
import { DataSupport } from "../pages/data-support/data-support.po";

const HUMANIZE = mockPlatformAgentAddon();
const TOOLKIT = mockPlatformAgentAddon({
  id: "55555555-5555-4555-8555-000000000002",
  kind: "git",
  name: "toolkit",
  spec: { url: "https://github.com/example/toolkit.git", commit: "7fd1a60b01f91b314f59955a4e4d4e80d8edf11d" },
  reason: "Shared drawing templates.",
  state: "APPROVED",
  organization_name: "Acme",
  agent_name: "Planner",
  agent_type: "openclaw",
  decided_at: "2026-10-22T09:00:00Z",
  decided_by: { full_name: "Platform Admin", email: "admin@example.com" },
});

test.describe("Platform add-on requests (platform_admin)", () => {
  let addonsPage: PlatformAgentAddonsPage;

  test.use({ storageState: { cookies: [], origins: [] } });

  test.beforeEach(async ({ page }) => {
    addonsPage = new PlatformAgentAddonsPage(page);
    const data = new DataSupport(page);
    await data.auth.interceptRefreshRequest();
    await data.users.interceptGetUserContextRequest({ userContext: { ...UserContext, is_platform_admin: true } });
    await data.users.interceptGetOrganizationsRequest();
  });

  test("lists pending requests by default with everything a reviewer needs", async ({ page }) => {
    const { listQueries } = await new AgentAddonDataSupport(page).interceptPlatformAddons({
      requests: [HUMANIZE, TOOLKIT],
    });

    await addonsPage.goto();

    await expect(addonsPage.heading()).toBeVisible();
    const request = addonsPage.request("humanize");
    await expect(request).toContainText("Example Co · Assistant · Hermes");
    await expect(request).toContainText("Python package");
    await expect(request).toContainText("humanize==4.12.3");
    await expect(request).toContainText(HUMANIZE.reason);
    await expect(request).toContainText("Requested by Grace Hopper");
    await expect(addonsPage.request("toolkit")).toHaveCount(0);
    expect(listQueries.at(-1)?.get("state")).toBe("PENDING");
    await expect(new AppNavigation(page).mainLink("Add-ons")).toHaveAttribute("aria-current", "page");
  });

  test("filters by state", async ({ page }) => {
    const { listQueries } = await new AgentAddonDataSupport(page).interceptPlatformAddons({
      requests: [HUMANIZE, TOOLKIT],
    });
    await addonsPage.goto();

    await addonsPage.filterState("Approved");

    await expect(addonsPage.request("toolkit")).toContainText("Acme · Planner · OpenClaw");
    await expect(addonsPage.request("humanize")).toHaveCount(0);
    expect(listQueries.at(-1)?.get("state")).toBe("APPROVED");

    await addonsPage.filterState("All states");

    await expect(addonsPage.request("humanize")).toBeVisible();
    expect(listQueries.at(-1)?.get("state")).toBeNull();
  });

  test("approves a pending request after confirming", async ({ page }) => {
    const { decisions } = await new AgentAddonDataSupport(page).interceptPlatformAddons({ requests: [HUMANIZE] });
    await addonsPage.goto("?state=ALL");

    await addonsPage.decide("humanize", "Approve");
    await expect(addonsPage.confirmation()).toContainText("next time that agent starts");
    await addonsPage.confirm("Approve");

    await expect(addonsPage.request("humanize")).toContainText("Approved");
    await expect(addonsPage.request("humanize").getByRole("button", { name: "Revoke" })).toBeVisible();
    expect(decisions).toEqual([{ addonId: HUMANIZE.id, action: "approve", body: null }]);
  });

  test("rejects a pending request only with a reason", async ({ page }) => {
    const { decisions } = await new AgentAddonDataSupport(page).interceptPlatformAddons({ requests: [HUMANIZE] });
    await addonsPage.goto("?state=ALL");

    await addonsPage.decide("humanize", "Reject");
    await expect(addonsPage.confirmation().getByRole("button", { name: "Reject" })).toBeDisabled();
    await addonsPage.confirmation().getByLabel("Reason").fill("Use the vendored copy instead.");
    await addonsPage.confirm("Reject");

    await expect(addonsPage.request("humanize")).toContainText("Rejected: Use the vendored copy instead.");
    expect(decisions).toEqual([
      { addonId: HUMANIZE.id, action: "reject", body: { reason: "Use the vendored copy instead." } },
    ]);
  });

  test("revokes an approved add-on", async ({ page }) => {
    const { decisions } = await new AgentAddonDataSupport(page).interceptPlatformAddons({ requests: [TOOLKIT] });
    await addonsPage.goto("?state=ALL");

    await addonsPage.decide("toolkit", "Revoke");
    await expect(addonsPage.confirmation()).toContainText("loses it the next time it starts");
    await addonsPage.confirm("Revoke");

    await expect(addonsPage.request("toolkit")).toContainText("Revoked");
    expect(decisions).toEqual([{ addonId: TOOLKIT.id, action: "revoke", body: null }]);
  });
});
