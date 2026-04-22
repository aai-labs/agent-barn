"use client";

import { useOrgStore } from "./org-store";

let hasInitializedStoreSync = false;

export function initStoreSync() {
  if (typeof window === "undefined" || hasInitializedStoreSync) {
    return;
  }

  hasInitializedStoreSync = true;
  window.addEventListener("storage", () => {
    void useOrgStore.persist.rehydrate();
  });
}

