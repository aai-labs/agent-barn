"use client";

import { formatSpend } from "../format";
import type { OrganizationSpend } from "../schemas";

interface OrganizationsBySpendProps {
  organizations: OrganizationSpend[];
  activeOrganizationId: string | null;
  onSelect: (organization: { id: string; name: string } | null) => void;
}

/** Organizations ranked by spend, doubling as a one-click filter.
 *
 *  The unattributed row is kept in the list rather than filtered out: without
 *  it, the rows here would not add up to the platform total shown above them. */
export function OrganizationsBySpend({
  organizations,
  activeOrganizationId,
  onSelect,
}: OrganizationsBySpendProps) {
  if (organizations.length === 0) return null;

  const top = organizations[0]?.spend ?? 0;

  return (
    <div className="af-card p-4 mb-6" data-testid="organizations-by-spend">
      <h2
        className="text-[14px] font-semibold m-0 mb-3"
        style={{ color: "var(--ink)" }}
      >
        Organizations by spend
      </h2>
      <div className="flex flex-col">
        {organizations.map((organization) => {
          const id = organization.organizationId;
          const isActive = id !== null && id === activeOrganizationId;
          const name = organization.organizationName ?? "Unattributed";
          const width = top > 0 ? (organization.spend / top) * 100 : 0;

          return (
            <button
              key={id ?? "unattributed"}
              type="button"
              // The unattributed bucket has no organization to filter by.
              disabled={id === null}
              onClick={() => onSelect(isActive ? null : { id: id!, name })}
              data-testid="organization-spend-row"
              className="relative grid grid-cols-[minmax(140px,1fr)_90px_90px_110px] items-center gap-3 px-2 py-2 text-left text-[13px] rounded disabled:cursor-default"
              style={{
                background: isActive ? "var(--surface-2)" : "transparent",
              }}
            >
              <span
                className="absolute inset-y-1 left-0 rounded pointer-events-none"
                style={{
                  width: `${width}%`,
                  background: "var(--ink-5)",
                  opacity: 0.12,
                }}
              />
              <span
                className="relative truncate"
                style={{ color: id ? "var(--ink)" : "var(--ink-4)" }}
                title={name}
              >
                {name}
              </span>
              <span className="relative text-right" style={{ color: "var(--ink-4)" }}>
                {organization.agents.toLocaleString()}{" "}
                {organization.agents === 1 ? "agent" : "agents"}
              </span>
              <span className="relative text-right" style={{ color: "var(--ink-4)" }}>
                {organization.calls.toLocaleString()}
              </span>
              <span
                className="relative text-right font-medium"
                style={{ color: "var(--ink)" }}
              >
                {formatSpend(organization.spend)}
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
