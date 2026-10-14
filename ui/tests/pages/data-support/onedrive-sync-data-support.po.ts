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

export class OneDriveSyncDataSupport extends BaseInterceptor {
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
