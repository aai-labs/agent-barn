import { expect, test } from "@playwright/test";

import UserContext from "../fixtures/user-context.json";
import { DataSupport } from "../pages/data-support/data-support.po";
import {
  ONEDRIVE_FOLDER_URL,
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

  test("an unfinished connection says no site has been chosen", async () => {
    await data.users.interceptGetUserContextRequest();
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
