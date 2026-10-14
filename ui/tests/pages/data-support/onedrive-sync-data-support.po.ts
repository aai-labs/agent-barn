import { BaseInterceptor } from "./base-intercepter.po";

export const ONEDRIVE_FOLDER_URL =
  "https://contoso.sharepoint.com/sites/AgentBarnTest/Shared%20Documents/Agent%20Barn";

/** An Organization's OneDrive sync status as the API returns it (snake_case). */
export function oneDriveSyncStatus(overrides: Record<string, unknown> = {}) {
  return {
    available: true,
    status: null,
    site_name: null,
    site_url: null,
    folder_web_url: null,
    connected_at: null,
    ...overrides,
  };
}

export function activeOneDriveSync(overrides: Record<string, unknown> = {}) {
  return oneDriveSyncStatus({
    status: "active",
    site_name: "Agent Barn Test",
    site_url: "https://contoso.sharepoint.com/sites/AgentBarnTest",
    folder_web_url: ONEDRIVE_FOLDER_URL,
    connected_at: "2026-10-14T10:00:00Z",
    ...overrides,
  });
}

export const ONEDRIVE_SITE = {
  id: "contoso.sharepoint.com,aaa,bbb",
  name: "Agent Barn Test",
  web_url: "https://contoso.sharepoint.com/sites/AgentBarnTest",
};

export type ConnectFlowRecord = {
  authorizeQuery?: URLSearchParams;
  signInBody?: Record<string, unknown>;
  searches: string[];
  siteBody?: Record<string, unknown>;
};

export class OneDriveSyncDataSupport extends BaseInterceptor {
  /**
   * The whole connect flow against a stateful status: the authorize URL, Microsoft's
   * redirect back to our callback page (posting `callbackMessage` to the opener), the
   * sign-in, the site search and the site choice. Records what the UI sent.
   */
  async interceptConnectFlow({
    initial = oneDriveSyncStatus(),
    callbackMessage = { code: "the-code", state: "the-state" },
    sites = [ONEDRIVE_SITE],
    chooseStatus = 200,
    chooseDetail = "Choosing the site failed",
  }: {
    initial?: Record<string, unknown>;
    callbackMessage?: Record<string, unknown>;
    sites?: Record<string, unknown>[];
    chooseStatus?: number;
    chooseDetail?: string;
  } = {}): Promise<ConnectFlowRecord> {
    const record: ConnectFlowRecord = { searches: [] };
    let current = initial;
    const base = "**/api/v1/organizations/*/onedrive-sync/connection";

    await this.page.route(base, async (route) => {
      if (route.request().method() !== "GET") return route.fallback();
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(current) });
    });
    await this.page.route(`${base}/authorize-url*`, async (route) => {
      const url = new URL(route.request().url());
      record.authorizeQuery = url.searchParams;
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ authorize_url: `${url.origin}/api/v1/integrations/onedrive-sync/callback?from=microsoft` }),
      });
    });
    // Stands in for Microsoft redirecting the popup back to our callback page.
    await this.page.context().route("**/api/v1/integrations/onedrive-sync/callback*", async (route) => {
      const message = JSON.stringify({ type: "onedrive-sync-oauth", ...callbackMessage });
      await route.fulfill({
        status: 200,
        contentType: "text/html",
        body: `<script>window.opener.postMessage(${message}, window.location.origin); window.close();</script>`,
      });
    });
    await this.page.route(`${base}/sign-in`, async (route) => {
      record.signInBody = route.request().postDataJSON() as Record<string, unknown>;
      current = oneDriveSyncStatus({ status: "pending" });
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(current) });
    });
    await this.page.route(`${base}/sites*`, async (route) => {
      record.searches.push(new URL(route.request().url()).searchParams.get("search") ?? "");
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(sites) });
    });
    await this.page.route(`${base}/site`, async (route) => {
      record.siteBody = route.request().postDataJSON() as Record<string, unknown>;
      if (chooseStatus >= 400) {
        await route.fulfill({ status: chooseStatus, contentType: "application/json", body: JSON.stringify({ detail: chooseDetail }) });
        return;
      }
      current = activeOneDriveSync();
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(current) });
    });
    return record;
  }

  async interceptStatus({
    connection = oneDriveSyncStatus(),
    status = 200,
    detail = "Unable to load OneDrive sync",
  }: {
    connection?: Record<string, unknown>;
    status?: number;
    detail?: string;
  } = {}) {
    await this.page.route("**/api/v1/organizations/*/onedrive-sync/connection", async (route) => {
      if (route.request().method() !== "GET") {
        await route.fallback();
        return;
      }
      await route.fulfill({
        status,
        contentType: "application/json",
        body: JSON.stringify(status >= 400 ? { detail } : connection),
      });
    });
  }
}
