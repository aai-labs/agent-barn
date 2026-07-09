import { create } from "zustand";

import { AuthTokens } from "@/shared/api/types";

interface AuthState {
  authToken: AuthTokens | null;
  isSessionExpired: boolean;
  setToken: (token: AuthTokens | null) => void;
  clearToken: () => void;
  expireSession: () => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  authToken: null,
  isSessionExpired: false,
  setToken: (token) => set({ authToken: token, isSessionExpired: false }),
  clearToken: () => set({ authToken: null }),
  expireSession: () => set({ authToken: null, isSessionExpired: true }),
}));
