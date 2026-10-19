import { BaseInterceptor } from "./base-intercepter.po";

export const ONEDRIVE_FOLDER_URL =
  "https://contoso.sharepoint.com/sites/AgentBarnTest/Shared%20Documents/Agent%20Barn";

export const ONEDRIVE_APPROVAL_URL =
  "https://login.microsoftonline.com/organizations/v2.0/adminconsent?client_id=app&scope=https%3A%2F%2Fgraph.microsoft.com%2F.default";

export const OTHER_DRIVE_FOLDER_URL = "https://otherdrive.example.test/Agent%20Barn";

export const ONEDRIVE_SITE = {
  id: "contoso.sharepoint.com,aaa,bbb",
  name: "Agent Barn Test",
  web_url: "https://contoso.sharepoint.com/sites/AgentBarnTest",
};

type Entry = Record<string, unknown>;

/** OneDrive as the provider list returns it (snake_case), not connected. */
export function oneDriveEntry(overrides: Entry = {}): Entry {
  return {
    key: "onedrive",
    display_name: "OneDrive",
    tagline: "Sync to a SharePoint site",
    folder_hint: "In OneDrive, choose Add shortcut to My files to keep this folder next to your own files.",
    connect_hint:
      "A Microsoft Global Administrator approves Agent Barn for your organization once, and the person connecting must be a SharePoint Administrator and a member of the site they pick.",
    location_noun: "SharePoint site",
    schema_version: 1,
    capabilities: ["admin_approval", "location_picker"],
    approval_url: ONEDRIVE_APPROVAL_URL,
    connection: null,
    can_connect: true,
    blocked_reason: null,
    ...overrides,
  };
}

/** A second provider with no location picker and no approval link, to prove the UI has no OneDrive branch. */
export function otherDriveEntry(overrides: Entry = {}): Entry {
  return {
    key: "otherdrive",
    display_name: "Other Drive",
    tagline: "Sync to Other Drive",
    folder_hint: "Open the folder in Other Drive.",
    connect_hint: null,
    location_noun: null,
    schema_version: 1,
    capabilities: [],
    approval_url: null,
    connection: null,
    can_connect: true,
    blocked_reason: null,
    ...overrides,
  };
}

export function pendingConnection(): Entry {
  return { status: "pending", location_name: null, location_url: null, folder_web_url: null, connected_at: null };
}

export function activeOneDriveConnection(): Entry {
  return {
    status: "active",
    location_name: ONEDRIVE_SITE.name,
    location_url: ONEDRIVE_SITE.web_url,
    folder_web_url: ONEDRIVE_FOLDER_URL,
    connected_at: "2026-10-16T10:00:00Z",
  };
}

export function activeOtherDriveConnection(): Entry {
  return {
    status: "active",
    location_name: null,
    location_url: null,
    folder_web_url: OTHER_DRIVE_FOLDER_URL,
    connected_at: "2026-10-16T10:00:00Z",
  };
}

export type ConnectFlowRecord = {
  authorizeQuery?: URLSearchParams;
  signInBody?: Record<string, unknown>;
  searches: string[];
  locationBody?: Record<string, unknown>;
  disconnectBody?: Record<string, unknown>;
  abandoned: boolean;
};

export class SyncProviderDataSupport extends BaseInterceptor {
  async interceptProviders({
    providers = [oneDriveEntry()],
    status = 200,
    detail = "Unable to load sync providers",
  }: {
    providers?: Entry[];
    status?: number;
    detail?: string;
  } = {}) {
    await this.page.route("**/api/v1/organizations/*/sync-providers", async (route) => {
      await route.fulfill({
        status,
        contentType: "application/json",
        body: JSON.stringify(status >= 400 ? { detail } : providers),
      });
    });
  }

  /**
   * One provider's whole flow against a stateful provider list: the authorize URL, the provider
   * redirecting the popup back to our callback page (posting `callbackMessage` to the opener),
   * the sign-in, the location search and choice, disconnect and start over. Records what the UI sent.
   */
  async interceptConnectFlow({
    providers = [oneDriveEntry()],
    providerKey = "onedrive",
    callbackMessage = { code: "the-code", state: "the-state" },
    locations = [ONEDRIVE_SITE],
    activeConnection = activeOneDriveConnection(),
    chooseStatus = 200,
    chooseDetail = "Choosing the location failed",
    disconnectStatus = 200,
    disconnectDetail = "Disconnecting failed",
  }: {
    providers?: Entry[];
    providerKey?: string;
    callbackMessage?: Record<string, unknown>;
    locations?: Record<string, unknown>[];
    activeConnection?: Entry;
    chooseStatus?: number;
    chooseDetail?: string;
    disconnectStatus?: number;
    disconnectDetail?: string;
  } = {}): Promise<ConnectFlowRecord> {
    const record: ConnectFlowRecord = { searches: [], abandoned: false };
    let current = providers.map((entry) => ({ ...entry }));
    const entry = () => current.find((item) => item.key === providerKey) as Entry;
    const update = (connection: Entry | null) => {
      current = current.map((item) =>
        item.key === providerKey ? { ...item, connection, can_connect: connection === null } : item,
      );
      return entry();
    };
    const json = (body: unknown) => ({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
    const base = `**/api/v1/organizations/*/sync-providers/${providerKey}/connection`;

    await this.page.route("**/api/v1/organizations/*/sync-providers", async (route) => {
      await route.fulfill(json(current));
    });
    await this.page.route(base, async (route) => {
      if (route.request().method() !== "DELETE") return route.fallback();
      record.abandoned = true;
      if ((entry().connection as Entry | null)?.status === "pending") update(null);
      await route.fulfill({ status: 204, body: "" });
    });
    await this.page.route(`${base}/authorize-url*`, async (route) => {
      const url = new URL(route.request().url());
      record.authorizeQuery = url.searchParams;
      await route.fulfill(
        json({ authorize_url: `${url.origin}/api/v1/integrations/sync-provider/${providerKey}/callback?from=provider` }),
      );
    });
    // Stands in for the provider redirecting the popup back to our callback page.
    await this.page.context().route(`**/api/v1/integrations/sync-provider/${providerKey}/callback*`, async (route) => {
      const message = JSON.stringify({ type: "sync-provider-oauth", ...callbackMessage });
      await route.fulfill({
        status: 200,
        contentType: "text/html",
        body: `<script>window.opener.postMessage(${message}, window.location.origin); window.close();</script>`,
      });
    });
    await this.page.route(`${base}/sign-in`, async (route) => {
      record.signInBody = route.request().postDataJSON() as Record<string, unknown>;
      const picker = (entry().capabilities as string[]).includes("location_picker");
      await route.fulfill(json(update(picker ? pendingConnection() : activeConnection)));
    });
    await this.page.route(`${base}/locations*`, async (route) => {
      record.searches.push(new URL(route.request().url()).searchParams.get("search") ?? "");
      await route.fulfill(json(locations));
    });
    await this.page.route(`${base}/location`, async (route) => {
      record.locationBody = route.request().postDataJSON() as Record<string, unknown>;
      if (chooseStatus >= 400) {
        await route.fulfill({ status: chooseStatus, contentType: "application/json", body: JSON.stringify({ detail: chooseDetail }) });
        return;
      }
      await route.fulfill(json(update(activeConnection)));
    });
    await this.page.route(`${base}/disconnect`, async (route) => {
      record.disconnectBody = route.request().postDataJSON() as Record<string, unknown>;
      if (disconnectStatus >= 400) {
        await route.fulfill({
          status: disconnectStatus,
          contentType: "application/json",
          body: JSON.stringify({ detail: disconnectDetail }),
        });
        return;
      }
      await route.fulfill(json(update(null)));
    });
    return record;
  }
}
