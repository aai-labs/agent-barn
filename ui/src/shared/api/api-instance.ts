import { createApiClient } from "./client/factory";
import { useAuthStore } from "@/auth/providers/auth-store";

// Header carrying the active organization on every request. Set by OrganizationProvider
// and cleared on logout; defined here so both agree on the exact name.
export const ORGANIZATION_HEADER = "X-Organization-Id";

const apiClient = createApiClient({ baseURL: "" });

apiClient.setupAuth({
  refreshUrl: "/api/v1/auth/refresh",
  getTokens: () => useAuthStore.getState().authToken,
  setTokens: (token) => useAuthStore.getState().setToken(token),
  clearTokens: () => useAuthStore.getState().clearToken(),
  onSessionExpired: () => useAuthStore.getState().expireSession(),
});

export { apiClient as api };
