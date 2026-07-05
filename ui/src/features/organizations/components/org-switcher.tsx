"use client";

import { useEffect, useRef, useState } from "react";
import { usePathname, useRouter } from "next/navigation";

import { BuildingIcon, CheckIcon, ChevronDownIcon } from "@/components/icons";
import { useOrganizationContext } from "@/features/organizations/providers/organization-provider";
import type { Organization } from "../schemas";

// Segments directly under /dashboard/ that are NOT an org id (global admin / personal).
const GLOBAL_DASHBOARD_SEGMENTS = new Set(["organizations", "account"]);

export function OrgSwitcher() {
  const { organizations, selectedOrganization } = useOrganizationContext();
  const router = useRouter();
  const pathname = usePathname() ?? "";
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const onSelect = (org: Organization) => {
    setOpen(false);
    if (org.id === selectedOrganization?.id) return;

    // Stay on the same sub-page under the new org by swapping the org segment; from a
    // global page (no org in the URL) land on the new org's home.
    const parts = pathname.split("/"); // ["", "dashboard", <seg>, ...]
    const isOrgScopedRoute =
      parts[1] === "dashboard" &&
      !!parts[2] &&
      !GLOBAL_DASHBOARD_SEGMENTS.has(parts[2]);

    if (isOrgScopedRoute) {
      parts[2] = org.id;
      router.push(parts.join("/"));
    } else {
      router.push(`/dashboard/${org.id}`);
    }
  };

  // Nothing to show (e.g. a superuser with no memberships) — the org is managed from
  // the Organizations page instead.
  if (organizations.length === 0 || !selectedOrganization) {
    return null;
  }

  // Only one org — show it as a static breadcrumb, no switcher affordance.
  if (organizations.length === 1) {
    return (
      <div
        className="flex items-center gap-1.5 text-[13px]"
        style={{ color: "var(--ink-3)" }}
      >
        <span style={{ color: "var(--ink-5)" }}>/</span>
        <span>{selectedOrganization.name}</span>
      </div>
    );
  }

  return (
    <div ref={ref} className="relative flex items-center gap-1.5">
      <span className="text-[13px]" style={{ color: "var(--ink-5)" }}>
        /
      </span>
      <button
        className="af-hover-bg flex items-center gap-1.5 rounded-lg px-2 py-[5px] text-[13px]"
        style={{ color: "var(--ink-2)" }}
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="listbox"
        aria-expanded={open}
      >
        <span className="max-w-[180px] truncate font-medium">
          {selectedOrganization.name}
        </span>
        <ChevronDownIcon size={13} style={{ color: "var(--ink-4)" }} />
      </button>

      {open && (
        <div
          role="listbox"
          className="absolute left-3 top-[calc(100%+8px)] z-50 max-h-80 w-64 overflow-y-auto rounded-xl py-1"
          style={{
            background: "var(--bg-elev)",
            border: "1px solid var(--line)",
            boxShadow: "var(--shadow-pop)",
          }}
        >
          <div
            className="px-3.5 py-1 text-[11px] font-semibold uppercase tracking-[0.08em]"
            style={{ color: "var(--ink-5)" }}
          >
            Organizations
          </div>
          {organizations.map((org) => {
            const isSelected = org.id === selectedOrganization.id;
            return (
              <button
                key={org.id}
                role="option"
                aria-selected={isSelected}
                className="af-hover-bg flex w-full items-center gap-2.5 px-3.5 py-2 text-left text-[13.5px]"
                style={{ color: "var(--ink-2)" }}
                onClick={() => onSelect(org)}
              >
                <BuildingIcon size={15} style={{ color: "var(--ink-4)" }} />
                <span className="flex-1 truncate">{org.name}</span>
                {isSelected && (
                  <CheckIcon size={15} style={{ color: "var(--ink)" }} />
                )}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
