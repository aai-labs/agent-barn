"use client";

import { createContext, useContext, useEffect, useMemo, useSyncExternalStore } from "react";
import type { ReactNode } from "react";

/**
 * Which dashboard navigation renders. `current` is the top bar the product ships;
 * `c` (one drill-in sidebar) and `d`/`d2` (rail and panel) are the concepts under
 * evaluation. The choice is a per-browser preview setting: it lives in localStorage,
 * and `?nav=c` (or `d`, `d2`, `current`) in any dashboard URL sets it, so a link can
 * open a given layout.
 */
export const NAV_VARIANTS = ["current", "c", "d", "d2"] as const;
export type NavVariant = (typeof NAV_VARIANTS)[number];

export const NAV_VARIANT_LABELS: Record<NavVariant, string> = {
  current: "Current top bar",
  c: "C · Drill-in sidebar",
  d: "D · Rail + panel",
  d2: "D2 · Rail + platform rail",
};

export const NAV_VARIANT_SHORT_LABELS: Record<NavVariant, string> = {
  current: "Current",
  c: "C",
  d: "D",
  d2: "D2",
};

const STORAGE_KEY = "agentbarn.nav-variant";
const CHANGE_EVENT = "agentbarn:nav-variant-change";
const DEFAULT_VARIANT: NavVariant = "current";

// Used when the browser refuses storage (private windows, blocked site data), so the
// switch still works for the current page load.
let memoryVariant: NavVariant = DEFAULT_VARIANT;

function isNavVariant(value: unknown): value is NavVariant {
  return typeof value === "string" && (NAV_VARIANTS as readonly string[]).includes(value);
}

function readVariant(): NavVariant {
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    return isNavVariant(stored) ? stored : memoryVariant;
  } catch {
    return memoryVariant;
  }
}

function writeVariant(variant: NavVariant) {
  memoryVariant = variant;
  try {
    window.localStorage.setItem(STORAGE_KEY, variant);
  } catch {
    // memoryVariant already holds it.
  }
  window.dispatchEvent(new Event(CHANGE_EVENT));
}

function subscribe(onChange: () => void) {
  window.addEventListener(CHANGE_EVENT, onChange);
  window.addEventListener("storage", onChange);
  return () => {
    window.removeEventListener(CHANGE_EVENT, onChange);
    window.removeEventListener("storage", onChange);
  };
}

type NavVariantContextValue = {
  variant: NavVariant;
  /**
   * True for every layout but `current`: their navigation lists the page's own
   * sections, so pages leave out their tab rows and section sidebars.
   */
  sectionsInNav: boolean;
  setVariant: (variant: NavVariant) => void;
};

const NavVariantContext = createContext<NavVariantContextValue>({
  variant: DEFAULT_VARIANT,
  sectionsInNav: false,
  setVariant: () => {},
});

export function NavVariantProvider({ children }: { children: ReactNode }) {
  const variant = useSyncExternalStore(subscribe, readVariant, () => DEFAULT_VARIANT);

  useEffect(() => {
    const requested = new URLSearchParams(window.location.search).get("nav");
    if (isNavVariant(requested)) writeVariant(requested);
  }, []);

  const value = useMemo(
    () => ({ variant, sectionsInNav: variant !== "current", setVariant: writeVariant }),
    [variant],
  );

  return <NavVariantContext.Provider value={value}>{children}</NavVariantContext.Provider>;
}

export function useNavVariant() {
  return useContext(NavVariantContext);
}
