"use client";

import { useCallback, useMemo } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

/**
 * Filter state that lives in the query string, for the cost surfaces.
 *
 * This exists because `nuqs`' `useQueryStates` wedges client navigation on
 * these pages: with five or more keys registered, leaving the page stops
 * working entirely — the Link fires and Next starts the transition, but the URL
 * never changes, so a reader is stuck on Costs until they reload. One key is
 * fine, which is why the rest of the app (a single `useQueryState` per page) is
 * unaffected. Upgrading nuqs 2.9.3 -> 2.10.1 did not help.
 *
 * The behaviour kept from nuqs is the part the pages actually depend on:
 * `replace` rather than `push`, so filtering does not fill the back button;
 * `scroll: false`, so changing a filter does not jump the page; and dropping a
 * key once it equals its default, so a clean filter state leaves a clean URL.
 *
 * `defaults` must be a stable reference — define it at module scope. It sets
 * both the keys this reads and the value each falls back to.
 */
export function useCostUrlFilters<T extends Record<string, string>>(
  defaults: T,
): readonly [T, (patch: Partial<Record<keyof T, string | null>>) => void] {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  // Keyed on the query string, not on the `searchParams` object. Next hands back
  // a fresh instance whenever the router re-renders, which in dev it does a few
  // times a second; depending on that identity rebuilt this object every time,
  // and a new object here becomes new filters, new query arguments and a fresh
  // render of every chart below. Comparing the string means an unchanged URL
  // returns the same object, and the work downstream simply does not happen.
  const query = searchParams.toString();

  const values = useMemo(() => {
    const params = new URLSearchParams(query);
    const next = {} as T;
    for (const key of Object.keys(defaults) as (keyof T)[]) {
      const raw = params.get(key as string);
      next[key] = (raw ?? defaults[key]) as T[keyof T];
    }
    return next;
  }, [query, defaults]);

  const setValues = useCallback(
    (patch: Partial<Record<keyof T, string | null>>) => {
      const next = new URLSearchParams(query);
      for (const [key, value] of Object.entries(patch)) {
        // A value equal to its default carries no information, so it is dropped
        // rather than written — otherwise clearing a filter would leave the URL
        // longer than it was before the filter was ever set.
        if (!value || value === defaults[key as keyof T]) next.delete(key);
        else next.set(key, value);
      }
      const nextQuery = next.toString();
      router.replace(nextQuery ? `${pathname}?${nextQuery}` : pathname, {
        scroll: false,
      });
    },
    [router, pathname, query, defaults],
  );

  return [values, setValues] as const;
}
