"use client";

import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";

type OrgStore = {
  selectedByUser: Record<string, string | null>;
  setOrganizationId: (userId: string, organizationId: string) => void;
  /**
   * An Organization this user is in the middle of deleting.
   * Used to prevent redirect to fallback org by OrganizationProvider.
   * Meaningful only between the delete and the route change.
   */
  deletingOrganizationId: string | null;
  setDeletingOrganizationId: (organizationId: string | null) => void;
};

export const useOrgStore = create<OrgStore>()(
  persist(
    (set) => ({
      selectedByUser: {},
      setOrganizationId: (userId: string, organizationId: string) =>
        set((state) => ({
          selectedByUser: {
            ...state.selectedByUser,
            [userId]: organizationId,
          },
        })),
      deletingOrganizationId: null,
      setDeletingOrganizationId: (organizationId: string | null) =>
        set({ deletingOrganizationId: organizationId }),
    }),
    {
      name: "org-storage",
      storage: createJSONStorage(() => localStorage),
      partialize: (state) => ({
        selectedByUser: state.selectedByUser,
      }),
    },
  ),
);

