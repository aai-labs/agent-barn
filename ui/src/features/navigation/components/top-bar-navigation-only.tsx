"use client";

import type { ReactNode } from "react";

import { useNavVariant } from "../providers/nav-variant-provider";

/** Renders its children only in the shipped top-bar layout, for links the others list. */
export function TopBarNavigationOnly({ children }: { children: ReactNode }) {
  const { sectionsInNav } = useNavVariant();
  return sectionsInNav ? null : <>{children}</>;
}
