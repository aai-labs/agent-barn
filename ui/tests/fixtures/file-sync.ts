export const MOCK_FOLDER_URL =
  "https://contoso.sharepoint.com/sites/AgentBarnTest/Shared%20Documents/Agent%20Barn/Maya";

export const ONEDRIVE = { key: "onedrive", display_name: "OneDrive" };

export function mockFileSyncStatus(overrides: Record<string, unknown> = {}) {
  return {
    enabled: true,
    state: "synced",
    provider: ONEDRIVE,
    folder_url: MOCK_FOLDER_URL,
    last_contact_at: "2026-10-26T09:30:00Z",
    retry_at: null,
    ...overrides,
  };
}
