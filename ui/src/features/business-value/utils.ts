import { createQueryKeyStructure } from "@/shared/query-keys";

export const organizationValueKey = createQueryKeyStructure("organization-value");
export const organizationActivityKey = createQueryKeyStructure("organization-activity");

export type KpiWindow = {
  fromDate?: string;
  toDate?: string;
};

export function windowQuery(range: KpiWindow): string {
  const params = new URLSearchParams();
  if (range.fromDate) params.set("from_date", range.fromDate);
  if (range.toDate) params.set("to_date", range.toDate);
  const query = params.toString();
  return query ? `?${query}` : "";
}

export function costsHref(orgBase: string, from: string, to: string): string {
  const params = new URLSearchParams();
  if (from) params.set("from", from);
  if (to) params.set("to", to);
  const query = params.toString();
  return query ? `${orgBase}/costs?${query}` : `${orgBase}/costs`;
}
