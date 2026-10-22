import { formatUsd } from "@/features/organizations/spend-limit";

import type { CreditKind } from "./schemas";

export const KIND_LABEL: Record<CreditKind, string> = {
  trial: "Trial credit",
  purchase: "Purchase",
  refund: "Refund",
  chargeback: "Disputed payment",
  adjustment: "Adjustment",
};

export function formatDate(iso: string) {
  const date = new Date(iso);
  return Number.isNaN(date.getTime())
    ? iso
    : date.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

export function signedUsd(value: number) {
  return `${value < 0 ? "−" : "+"}${formatUsd(Math.abs(value), 2)}`;
}
