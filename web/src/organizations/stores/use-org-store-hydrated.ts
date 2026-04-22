"use client";

import { useEffect, useState } from "react";

import { useOrgStore } from "./org-store";

export function useOrgStoreHydrated() {
  const [hasHydrated, setHasHydrated] = useState(() =>
    useOrgStore.persist.hasHydrated(),
  );

  useEffect(() => {
    const unsubscribeHydrate = useOrgStore.persist.onHydrate(() => {
      setHasHydrated(false);
    });
    const unsubscribeFinishHydration = useOrgStore.persist.onFinishHydration(() => {
      setHasHydrated(true);
    });

    return () => {
      unsubscribeHydrate();
      unsubscribeFinishHydration();
    };
  }, []);

  return hasHydrated;
}
