"use client";

import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";

type OrgStore = {
  selectedByUser: Record<string, string | null>;
  setOrganizationId: (userId: string, organizationId: string) => void;
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

