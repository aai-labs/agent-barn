import { expect, test, type Page } from "@playwright/test";

import UserContext from "../fixtures/user-context.json";
import { DataSupport } from "../pages/data-support/data-support.po";
import {
  ONEDRIVE_APPROVAL_URL,
  ONEDRIVE_FOLDER_URL,
  ONEDRIVE_SITE,
  OTHER_DRIVE_FOLDER_URL,
  activeOneDriveConnection,
  activeOtherDriveConnection,
  oneDriveEntry,
  otherDriveEntry,
  pendingConnection,
  unavailableOneDriveEntry,
} from "../pages/data-support/sync-provider-data-support.po";
import { SettingsSyncPage } from "../pages/settings-sync.po";

const ONEDRIVE = "OneDrive";
const OTHER_DRIVE = "Other Drive";
const SITE_NOUN = "SharePoint site";

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

let data: DataSupport;
let sync: SettingsSyncPage;

async function setUp(page: Page) {
  data = new DataSupport(page);
  sync = new SettingsSyncPage(page);
  await data.auth.interceptRefreshRequest();
  await data.users.interceptGetOrganizationsRequest();
  await data.organizations.interceptGetOrganization();
}

test.describe("Settings · Sync · the provider list", () => {
  test.use({ storageState: { cookies: [], origins: [] } });
  test.beforeEach(async ({ page }) => setUp(page));

  test("lists each offered provider with its tagline", async ({ page }) => {
    await data.users.interceptGetUserContextRequest();
    await data.syncProviders.interceptProviders();

    await sync.open();

    await expect(sync.rows).toHaveCount(1);
    await expect(sync.row(ONEDRIVE)).toContainText("Sync to a SharePoint site");
    await expect(
      page.getByText("Connect storage providers to keep your organization's files in sync."),
    ).toBeVisible();
  });

  test("OneDrive shows its logo and a provider without one shows its initial", async () => {
    await data.users.interceptGetUserContextRequest();
    await data.syncProviders.interceptProviders({ providers: [oneDriveEntry(), otherDriveEntry()] });

    await sync.open();

    const logo = sync.row(ONEDRIVE).getByRole("img", { name: "OneDrive" });
    await expect(logo).toBeVisible();
    await expect.poll(() => logo.evaluate((image: HTMLImageElement) => image.naturalWidth)).toBeGreaterThan(0);
    await expect(sync.row(OTHER_DRIVE).getByRole("img")).toHaveCount(0);
    await expect(sync.row(OTHER_DRIVE)).toContainText("O");
  });

  test("says so when no provider is offered on this server", async () => {
    await data.users.interceptGetUserContextRequest();
    await data.syncProviders.interceptProviders({ providers: [] });

    await sync.open();

    await expect(sync.section).toContainText("No sync providers are available on this server.");
    await expect(sync.rows).toHaveCount(0);
  });

  test("a connected provider shows where it syncs, the folder link and the hint", async () => {
    await data.users.interceptGetUserContextRequest();
    await data.syncProviders.interceptProviders({
      providers: [oneDriveEntry({ connection: activeOneDriveConnection(), can_connect: false })],
    });

    await sync.open();

    await expect(sync.row(ONEDRIVE)).toContainText("Connected to Agent Barn Test");
    await expect(sync.openFolder(ONEDRIVE)).toHaveAttribute("href", ONEDRIVE_FOLDER_URL);
    await expect(sync.openFolder(ONEDRIVE)).toHaveAttribute("target", "_blank");
    await expect(sync.openFolder(ONEDRIVE)).toHaveText("Open in OneDrive");
    await expect(sync.row(ONEDRIVE)).toContainText("Add shortcut to My files");
    await expect(sync.connect(ONEDRIVE)).toHaveCount(0);
  });

  test("an Owner sees who must approve, the approval link and Connect", async () => {
    await data.users.interceptGetUserContextRequest();
    await data.syncProviders.interceptProviders();

    await sync.open();

    await expect(sync.row(ONEDRIVE)).toContainText("Microsoft Global Administrator");
    await expect(sync.row(ONEDRIVE)).toContainText("SharePoint Administrator");
    await expect(sync.approvalLink(ONEDRIVE)).toHaveAttribute("href", ONEDRIVE_APPROVAL_URL);
    await expect(sync.approvalLink(ONEDRIVE)).toHaveAttribute("target", "_blank");
    await expect(sync.connect(ONEDRIVE)).toBeEnabled();
  });

  test("a Member can see the list but not connect or approve", async () => {
    await data.users.interceptGetUserContextRequest({ userContext: memberContext() });
    await data.syncProviders.interceptProviders();

    await sync.open();

    await expect(sync.sidebarItem).toBeVisible();
    await expect(sync.row(ONEDRIVE)).toContainText("An Organization Owner or Admin can connect.");
    await expect(sync.connect(ONEDRIVE)).toHaveCount(0);
    await expect(sync.approvalLink(ONEDRIVE)).toHaveCount(0);
  });

  test("a Member opens the connected folder but cannot disconnect", async () => {
    await data.users.interceptGetUserContextRequest({ userContext: memberContext() });
    await data.syncProviders.interceptProviders({
      providers: [oneDriveEntry({ connection: activeOneDriveConnection(), can_connect: false })],
    });

    await sync.open();

    await expect(sync.openFolder(ONEDRIVE)).toHaveAttribute("href", ONEDRIVE_FOLDER_URL);
    await expect(sync.disconnect(ONEDRIVE)).toHaveCount(0);
  });

  test("a Member sees that an unfinished connection has no location yet", async () => {
    await data.users.interceptGetUserContextRequest({ userContext: memberContext() });
    await data.syncProviders.interceptProviders({
      providers: [oneDriveEntry({ connection: pendingConnection(), can_connect: false })],
    });

    await sync.open();

    await expect(sync.row(ONEDRIVE)).toContainText("no SharePoint site has been chosen yet");
    await expect(sync.locationSearch(ONEDRIVE, SITE_NOUN)).toHaveCount(0);
  });

  for (const [role, userContext] of [
    ["an Owner", UserContext],
    ["a Member", memberContext()],
  ] as const) {
    test(`${role} is told a provider isn't configured for the platform`, async () => {
      await data.users.interceptGetUserContextRequest({ userContext });
      await data.syncProviders.interceptProviders({ providers: [unavailableOneDriveEntry()] });

      await sync.open();

      await expect(sync.row(ONEDRIVE)).toContainText("OneDrive is not configured for the platform.");
      await expect(sync.row(ONEDRIVE)).not.toContainText("ONEDRIVE_SYNC_CLIENT_ID");
      await expect(sync.connect(ONEDRIVE)).toHaveCount(0);
      await expect(sync.approvalLink(ONEDRIVE)).toHaveCount(0);
    });
  }

  test("a list that fails to load can be retried", async () => {
    await data.users.interceptGetUserContextRequest();
    await data.syncProviders.interceptProviders({ status: 500 });

    await sync.open();

    await expect(sync.retry).toBeVisible();
  });

  test("another provider stays blocked while one is connected, with the server's reason", async () => {
    await data.users.interceptGetUserContextRequest();
    await data.syncProviders.interceptProviders({
      providers: [
        oneDriveEntry({ connection: activeOneDriveConnection(), can_connect: false }),
        otherDriveEntry({ can_connect: false, blocked_reason: "Disconnect OneDrive first." }),
      ],
    });

    await sync.open();

    await expect(sync.rows).toHaveCount(2);
    await expect(sync.connect(OTHER_DRIVE)).toBeDisabled();
    await expect(sync.row(OTHER_DRIVE)).toContainText("Disconnect OneDrive first.");
    await expect(sync.row(OTHER_DRIVE)).toContainText("Sync to Other Drive");
    await expect(sync.approvalLink(OTHER_DRIVE)).toHaveCount(0);
  });

  test("a provider without a location picker shows no picker while pending", async () => {
    await data.users.interceptGetUserContextRequest();
    await data.syncProviders.interceptProviders({
      providers: [otherDriveEntry({ connection: pendingConnection(), can_connect: false })],
    });

    await sync.open();

    await expect(sync.row(OTHER_DRIVE).getByRole("textbox")).toHaveCount(0);
    await expect(sync.startOver(OTHER_DRIVE)).toBeVisible();
  });
});

test.describe("Settings · Sync · connecting", () => {
  test.use({ storageState: { cookies: [], origins: [] } });
  test.beforeEach(async ({ page }) => setUp(page));

  test("an Owner connects OneDrive, picks a site and gets the folder link", async ({ page }) => {
    await data.users.interceptGetUserContextRequest();
    const record = await data.syncProviders.interceptConnectFlow();
    await sync.open();

    await sync.connect(ONEDRIVE).click();

    await expect(sync.locationSearch(ONEDRIVE, SITE_NOUN)).toBeVisible();
    expect(record.authorizeQuery?.get("purpose")).toBe("connect");
    expect(record.signInBody).toEqual({ code: "the-code", state: "the-state" });

    await sync.searchLocations(ONEDRIVE, SITE_NOUN, "Agent Barn");
    await expect(sync.row(ONEDRIVE)).toContainText(ONEDRIVE_SITE.web_url);
    expect(record.searches).toEqual(["Agent Barn"]);

    await sync.useLocation(ONEDRIVE, ONEDRIVE_SITE.name).click();

    await expect(sync.openFolder(ONEDRIVE)).toHaveAttribute("href", ONEDRIVE_FOLDER_URL);
    await expect(sync.row(ONEDRIVE)).toContainText("Connected to Agent Barn Test");
    expect(record.locationBody).toEqual({ location_id: ONEDRIVE_SITE.id });
    // The closing picker must not search again: the connection is no longer pending.
    await page.waitForLoadState("networkidle");
    expect(record.searches).toEqual(["Agent Barn"]);
  });

  test("a provider without a location picker is connected straight after sign-in", async () => {
    await data.users.interceptGetUserContextRequest();
    const record = await data.syncProviders.interceptConnectFlow({
      providers: [otherDriveEntry()],
      providerKey: "otherdrive",
      activeConnection: activeOtherDriveConnection(),
    });
    await sync.open();

    await sync.connect(OTHER_DRIVE).click();

    await expect(sync.openFolder(OTHER_DRIVE)).toHaveAttribute("href", OTHER_DRIVE_FOLDER_URL);
    await expect(sync.row(OTHER_DRIVE)).toContainText("Connected");
    expect(record.searches).toEqual([]);
  });

  test("an unfinished connection resumes at the site picker", async () => {
    await data.users.interceptGetUserContextRequest();
    await data.syncProviders.interceptConnectFlow({
      providers: [oneDriveEntry({ connection: pendingConnection(), can_connect: false })],
    });

    await sync.open();

    await expect(sync.locationSearch(ONEDRIVE, SITE_NOUN)).toBeVisible();
    await expect(sync.connect(ONEDRIVE)).toHaveCount(0);
  });

  test("searching needs a term", async () => {
    await data.users.interceptGetUserContextRequest();
    await data.syncProviders.interceptConnectFlow({
      providers: [oneDriveEntry({ connection: pendingConnection(), can_connect: false })],
    });
    await sync.open();

    await expect(sync.searchButton(ONEDRIVE)).toBeDisabled();
    await sync.locationSearch(ONEDRIVE, SITE_NOUN).fill("   ");
    await expect(sync.searchButton(ONEDRIVE)).toBeDisabled();
  });

  test("Microsoft asking for an administrator's approval is explained", async () => {
    await data.users.interceptGetUserContextRequest();
    await data.syncProviders.interceptConnectFlow({
      callbackMessage: { error: "A Microsoft Global Administrator needs to approve Agent Barn for your organization." },
    });
    await sync.open();

    await sync.connect(ONEDRIVE).click();

    await expect(sync.error(ONEDRIVE)).toContainText("A Microsoft Global Administrator needs to approve Agent Barn");
    await expect(sync.connect(ONEDRIVE)).toBeVisible();
  });

  test("a site the server refuses shows why", async () => {
    await data.users.interceptGetUserContextRequest();
    await data.syncProviders.interceptConnectFlow({
      providers: [oneDriveEntry({ connection: pendingConnection(), can_connect: false })],
      chooseStatus: 409,
      chooseDetail:
        "An Agent in this Organization already has SharePoint access to this site. Remove it there, or pick another site.",
    });
    await sync.open();

    await sync.searchLocations(ONEDRIVE, SITE_NOUN, "Agent");
    await sync.useLocation(ONEDRIVE, ONEDRIVE_SITE.name).click();

    await expect(sync.error(ONEDRIVE)).toContainText("already has SharePoint access to this site");
    await expect(sync.locationSearch(ONEDRIVE, SITE_NOUN)).toBeVisible();
  });

  test("a Member cannot connect or pick a site", async () => {
    await data.users.interceptGetUserContextRequest({ userContext: memberContext() });
    await data.syncProviders.interceptConnectFlow({
      providers: [oneDriveEntry({ connection: pendingConnection(), can_connect: false })],
    });

    await sync.open();

    await expect(sync.connect(ONEDRIVE)).toHaveCount(0);
    await expect(sync.locationSearch(ONEDRIVE, SITE_NOUN)).toHaveCount(0);
  });
});

test.describe("Settings · Sync · disconnecting", () => {
  test.use({ storageState: { cookies: [], origins: [] } });
  test.beforeEach(async ({ page }) => setUp(page));

  test("an Owner confirms, signs in with Microsoft and the connection ends", async () => {
    await data.users.interceptGetUserContextRequest();
    const record = await data.syncProviders.interceptConnectFlow({
      providers: [oneDriveEntry({ connection: activeOneDriveConnection(), can_connect: false })],
    });
    await sync.open();

    await sync.disconnect(ONEDRIVE).click();
    await expect(sync.dialog).toContainText("The Agent Barn folder and its files stay where they are");
    await sync.dialog.getByRole("button", { name: "Disconnect", exact: true }).click();

    await expect(sync.connect(ONEDRIVE)).toBeVisible();
    await expect(sync.openFolder(ONEDRIVE)).toHaveCount(0);
    expect(record.authorizeQuery?.get("purpose")).toBe("disconnect");
    expect(record.disconnectBody).toEqual({ code: "the-code", state: "the-state" });
  });

  test("a disconnect the provider refuses keeps the connection and says why", async () => {
    await data.users.interceptGetUserContextRequest();
    await data.syncProviders.interceptConnectFlow({
      providers: [oneDriveEntry({ connection: activeOneDriveConnection(), can_connect: false })],
      disconnectStatus: 403,
      disconnectDetail: "Sign in as a SharePoint administrator who is a member of this site, then try again.",
    });
    await sync.open();

    await sync.confirmDisconnect(ONEDRIVE);

    await expect(sync.error(ONEDRIVE)).toContainText("SharePoint administrator who is a member of this site");
    await expect(sync.openFolder(ONEDRIVE)).toBeVisible();
  });

  test("an unfinished connection can be started over", async () => {
    await data.users.interceptGetUserContextRequest();
    const record = await data.syncProviders.interceptConnectFlow({
      providers: [oneDriveEntry({ connection: pendingConnection(), can_connect: false })],
    });
    await sync.open();

    await sync.startOver(ONEDRIVE).click();

    await expect(sync.connect(ONEDRIVE)).toBeVisible();
    await expect(sync.locationSearch(ONEDRIVE, SITE_NOUN)).toHaveCount(0);
    expect(record.abandoned).toBe(true);
  });
});
