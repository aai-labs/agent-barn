import { createApiClient } from "./client/factory";
import { useAuthStore } from "@/auth/providers/auth-store";

const apiClient = createApiClient({ baseURL: "" });

apiClient.setupAuth({
  refreshUrl: "/api/v1/auth/refresh",
  getTokens: () => useAuthStore.getState().authToken,
  setTokens: (token) => useAuthStore.getState().setToken(token),
  clearTokens: () => useAuthStore.getState().clearToken(),
  onSessionExpired: () => useAuthStore.getState().expireSession(),
});

export { apiClient as api };
