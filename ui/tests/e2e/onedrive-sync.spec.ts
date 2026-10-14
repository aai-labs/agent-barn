import { expect, test } from "@playwright/test";

import UserContext from "../fixtures/user-context.json";
import { DataSupport } from "../pages/data-support/data-support.po";
import {
  ONEDRIVE_APPROVAL_URL,
  ONEDRIVE_FOLDER_URL,
  ONEDRIVE_SITE,
  activeOneDriveSync,
  oneDriveSyncStatus,
} from "../pages/data-support/onedrive-sync-data-support.po";
import { SettingsOneDriveSyncPage } from "../pages/settings-onedrive-sync.po";

/** The default fixture is a platform-admin Owner; a Member needs both stripped. */
function memberContext() {
  return {
    ...UserContext,
    is_platform_admin: false,
    organization_users: UserContext.organization_users.map((membership) => ({
      ...membership,
      role: "MEMBER",
    })),
  };
}

test.describe("Settings · OneDrive", () => {
  let data: DataSupport;
  let oneDrive: SettingsOneDriveSyncPage;
  test.use({ storageState: { cookies: [], origins: [] } });

  test.beforeEach(async ({ page }) => {
    data = new DataSupport(page);
    oneDrive = new SettingsOneDriveSyncPage(page);
    await data.auth.interceptRefreshRequest();
    await data.users.interceptGetOrganizationsRequest();
    await data.organizations.interceptGetOrganization();
  });

  test("says so when the server has no OneDrive sync app", async () => {
    await data.users.interceptGetUserContextRequest();
    await data.oneDriveSync.interceptStatus({ connection: oneDriveSyncStatus({ available: false }) });

    await oneDrive.open();

    await expect(oneDrive.section).toContainText("OneDrive sync isn't available on this server.");
    await expect(oneDrive.openInOneDrive).toHaveCount(0);
  });

  test("tells an Owner who has to approve before connecting", async () => {
    await data.users.interceptGetUserContextRequest();
    await data.oneDriveSync.interceptStatus();

    await oneDrive.open();

    await expect(oneDrive.section).toContainText("Not connected");
    await expect(oneDrive.section).toContainText("Microsoft Global Administrator");
    await expect(oneDrive.section).toContainText("SharePoint Administrator");
  });

  test("an Owner can forward the one-time approval link to a Global Administrator", async () => {
    await data.users.interceptGetUserContextRequest();
    await data.oneDriveSync.interceptStatus();

    await oneDrive.open();

    await expect(oneDrive.approvalLink).toHaveAttribute("href", ONEDRIVE_APPROVAL_URL);
    await expect(oneDrive.approvalLink).toHaveAttribute("target", "_blank");
  });

  test("a Member is not given the approval link", async () => {
    await data.users.interceptGetUserContextRequest({ userContext: memberContext() });
    await data.oneDriveSync.interceptStatus();

    await oneDrive.open();

    await expect(oneDrive.section).toContainText("Not connected");
    await expect(oneDrive.approvalLink).toHaveCount(0);
  });

  test("tells a Member who can connect", async () => {
    await data.users.interceptGetUserContextRequest({ userContext: memberContext() });
    await data.oneDriveSync.interceptStatus();

    await oneDrive.open();

    await expect(oneDrive.section).toContainText("Not connected");
    await expect(oneDrive.section).toContainText("An Organization Owner or Admin can connect OneDrive.");
  });

  test("a Member sees the section and opens the connected folder", async () => {
    await data.users.interceptGetUserContextRequest({ userContext: memberContext() });
    await data.oneDriveSync.interceptStatus({ connection: activeOneDriveSync() });

    await oneDrive.open();

    await expect(oneDrive.sidebarItem).toBeVisible();
    await expect(oneDrive.section).toContainText("Agent Barn Test");
    await expect(oneDrive.openInOneDrive).toHaveAttribute("href", ONEDRIVE_FOLDER_URL);
    await expect(oneDrive.openInOneDrive).toHaveAttribute("target", "_blank");
    await expect(oneDrive.section).toContainText("Add shortcut to My files");
  });

  test("a Member sees that an unfinished connection has no site yet", async () => {
    await data.users.interceptGetUserContextRequest({ userContext: memberContext() });
    await data.oneDriveSync.interceptStatus({ connection: oneDriveSyncStatus({ status: "pending" }) });

    await oneDrive.open();

    await expect(oneDrive.section).toContainText("no SharePoint site has been chosen yet");
  });

  test("a status that fails to load can be retried", async () => {
    await data.users.interceptGetUserContextRequest();
    await data.oneDriveSync.interceptStatus({ status: 500 });

    await oneDrive.open();

    await expect(oneDrive.retry).toBeVisible();
  });
});

test.describe("Settings · OneDrive · connecting", () => {
  let data: DataSupport;
  let oneDrive: SettingsOneDriveSyncPage;
  test.use({ storageState: { cookies: [], origins: [] } });

  test.beforeEach(async ({ page }) => {
    data = new DataSupport(page);
    oneDrive = new SettingsOneDriveSyncPage(page);
    await data.auth.interceptRefreshRequest();
    await data.users.interceptGetOrganizationsRequest();
    await data.organizations.interceptGetOrganization();
  });

  test("an Owner connects through Microsoft, picks a site and gets the folder link", async ({ page }) => {
    await data.users.interceptGetUserContextRequest();
    const record = await data.oneDriveSync.interceptConnectFlow();
    await oneDrive.open();

    await oneDrive.connect.click();

    await expect(oneDrive.siteSearch).toBeVisible();
    expect(record.authorizeQuery?.get("purpose")).toBe("connect");
    expect(record.signInBody).toEqual({ code: "the-code", state: "the-state" });

    await oneDrive.searchSites("Agent Barn");
    await expect(oneDrive.section).toContainText(ONEDRIVE_SITE.web_url);
    expect(record.searches).toEqual(["Agent Barn"]);

    await oneDrive.useSite(ONEDRIVE_SITE.name).click();

    await expect(oneDrive.openInOneDrive).toHaveAttribute("href", ONEDRIVE_FOLDER_URL);
    expect(record.siteBody).toEqual({ site_id: ONEDRIVE_SITE.id });
    // The closing picker must not search again: the connection is no longer pending.
    await page.waitForLoadState("networkidle");
    expect(record.searches).toEqual(["Agent Barn"]);
  });

  test("an unfinished connection resumes at the site picker", async () => {
    await data.users.interceptGetUserContextRequest();
    await data.oneDriveSync.interceptConnectFlow({ initial: oneDriveSyncStatus({ status: "pending" }) });

    await oneDrive.open();

    await expect(oneDrive.siteSearch).toBeVisible();
    await expect(oneDrive.connect).toHaveCount(0);
  });

  test("searching needs a term", async () => {
    await data.users.interceptGetUserContextRequest();
    await data.oneDriveSync.interceptConnectFlow({ initial: oneDriveSyncStatus({ status: "pending" }) });
    await oneDrive.open();

    await expect(oneDrive.searchButton).toBeDisabled();
    await oneDrive.siteSearch.fill("   ");
    await expect(oneDrive.searchButton).toBeDisabled();
  });

  test("Microsoft asking for an administrator's approval is explained", async () => {
    await data.users.interceptGetUserContextRequest();
    await data.oneDriveSync.interceptConnectFlow({
      callbackMessage: { error: "A Microsoft Global Administrator needs to approve Agent Barn for your organization." },
    });
    await oneDrive.open();

    await oneDrive.connect.click();

    await expect(oneDrive.error).toContainText("A Microsoft Global Administrator needs to approve Agent Barn");
    await expect(oneDrive.connect).toBeVisible();
  });

  test("a site the server refuses shows why", async () => {
    await data.users.interceptGetUserContextRequest();
    await data.oneDriveSync.interceptConnectFlow({
      initial: oneDriveSyncStatus({ status: "pending" }),
      chooseStatus: 409,
      chooseDetail: "An Agent in this Organization already has SharePoint access to this site. Remove it there, or pick another site.",
    });
    await oneDrive.open();

    await oneDrive.searchSites("Agent");
    await oneDrive.useSite(ONEDRIVE_SITE.name).click();

    await expect(oneDrive.error).toContainText("already has SharePoint access to this site");
    await expect(oneDrive.siteSearch).toBeVisible();
  });

  test("a Member cannot connect or pick a site", async () => {
    await data.users.interceptGetUserContextRequest({ userContext: memberContext() });
    await data.oneDriveSync.interceptConnectFlow({ initial: oneDriveSyncStatus({ status: "pending" }) });

    await oneDrive.open();

    await expect(oneDrive.connect).toHaveCount(0);
    await expect(oneDrive.siteSearch).toHaveCount(0);
  });

  test("there is nothing to connect when the server has no app", async () => {
    await data.users.interceptGetUserContextRequest();
    await data.oneDriveSync.interceptConnectFlow({ initial: oneDriveSyncStatus({ available: false }) });

    await oneDrive.open();

    await expect(oneDrive.connect).toHaveCount(0);
  });
});

test.describe("Settings · OneDrive · disconnecting", () => {
  let data: DataSupport;
  let oneDrive: SettingsOneDriveSyncPage;
  test.use({ storageState: { cookies: [], origins: [] } });

  test.beforeEach(async ({ page }) => {
    data = new DataSupport(page);
    oneDrive = new SettingsOneDriveSyncPage(page);
    await data.auth.interceptRefreshRequest();
    await data.users.interceptGetOrganizationsRequest();
    await data.organizations.interceptGetOrganization();
  });

  test("an Owner confirms, signs in with Microsoft and the connection ends", async () => {
    await data.users.interceptGetUserContextRequest();
    const record = await data.oneDriveSync.interceptConnectFlow({ initial: activeOneDriveSync() });
    await oneDrive.open();

    await oneDrive.disconnect.click();
    await expect(oneDrive.dialog).toContainText("The Agent Barn folder and its files stay in SharePoint");
    await oneDrive.dialog.getByRole("button", { name: "Disconnect", exact: true }).click();

    await expect(oneDrive.connect).toBeVisible();
    await expect(oneDrive.openInOneDrive).toHaveCount(0);
    expect(record.authorizeQuery?.get("purpose")).toBe("disconnect");
    expect(record.disconnectBody).toEqual({ code: "the-code", state: "the-state" });
  });

  test("a disconnect Microsoft refuses keeps the connection and says why", async () => {
    await data.users.interceptGetUserContextRequest();
    await data.oneDriveSync.interceptConnectFlow({
      initial: activeOneDriveSync(),
      disconnectStatus: 403,
      disconnectDetail: "Sign in as a SharePoint administrator who is a member of this site, then try again.",
    });
    await oneDrive.open();

    await oneDrive.confirmDisconnect();

    await expect(oneDrive.error).toContainText("SharePoint administrator who is a member of this site");
    await expect(oneDrive.openInOneDrive).toBeVisible();
  });

  test("a Member cannot disconnect", async () => {
    await data.users.interceptGetUserContextRequest({ userContext: memberContext() });
    await data.oneDriveSync.interceptConnectFlow({ initial: activeOneDriveSync() });

    await oneDrive.open();

    await expect(oneDrive.openInOneDrive).toBeVisible();
    await expect(oneDrive.disconnect).toHaveCount(0);
  });

  test("an unfinished connection can be started over", async () => {
    await data.users.interceptGetUserContextRequest();
    const record = await data.oneDriveSync.interceptConnectFlow({ initial: oneDriveSyncStatus({ status: "pending" }) });
    await oneDrive.open();

    await oneDrive.startOver.click();

    await expect(oneDrive.connect).toBeVisible();
    await expect(oneDrive.siteSearch).toHaveCount(0);
    expect(record.abandoned).toBe(true);
  });
});
