"use client";

import { useState } from "react";
import { Building2, Check, ChevronsUpDown, Plus, Shield } from "lucide-react";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { CreateOrganizationDialog } from "@/features/organizations/components/create-organization-dialog";
import { useOrganizationSwitch } from "@/features/organizations/hooks/use-organization-switch";

import { organizationInitials } from "../utils";

/**
 * Which Organization (or Platform View) the navigation is showing, and the one place
 * to switch it: a tile at the top of the rail, a card at the top of C's sidebar, or the
 * first step of D2's top-bar path.
 */
export function ContextSwitcher({
  appearance = "tile",
}: {
  appearance?: "tile" | "card" | "crumb";
}) {
  const {
    organizations,
    selectedOrganization,
    isPlatformView,
    isPlatformAdmin,
    canCreateOrganization,
    selectOrganization,
    selectPlatform,
  } = useOrganizationSwitch();
  const [createOpen, setCreateOpen] = useState(false);
  const label = isPlatformView ? "Platform admin" : (selectedOrganization?.name ?? "Organizations");

  return (
    <>
      {/* Not modal, so opening the create dialog from it leaves the page interactive. */}
      <DropdownMenu modal={false}>
        <DropdownMenuTrigger asChild>
          {appearance === "crumb" ? (
            <button
              type="button"
              aria-label={`Switch organization. Current: ${label}`}
              className="af-hover-bg flex min-w-0 items-center gap-2 rounded-lg px-2 py-1.5 text-[14px] font-semibold"
              style={{ color: isPlatformView ? "var(--accent-ink)" : "var(--ink)" }}
            >
              <span
                className="grid h-6 w-6 flex-shrink-0 place-items-center rounded-md text-[10.5px] font-bold"
                style={
                  isPlatformView
                    ? { background: "var(--accent-color)", color: "#fff" }
                    : { background: "var(--ink)", color: "var(--bg)" }
                }
              >
                {isPlatformView ? <Shield size={13} aria-hidden /> : organizationInitials(label)}
              </span>
              <span className="max-w-[220px] truncate">{label}</span>
              <ChevronsUpDown size={14} aria-hidden style={{ color: "var(--ink-4)" }} />
            </button>
          ) : appearance === "card" ? (
            <button
              type="button"
              aria-label={`Switch organization. Current: ${label}`}
              className="af-hover-bg flex w-full items-center gap-2.5 rounded-[10px] p-2 text-left"
              style={
                isPlatformView
                  ? { background: "var(--accent-soft)", border: "1px solid color-mix(in srgb, var(--accent-color) 22%, transparent)" }
                  : { background: "var(--bg-elev)", border: "1px solid var(--line)" }
              }
            >
              <span
                className="grid h-8 w-8 flex-shrink-0 place-items-center rounded-[9px] text-[12px] font-bold"
                style={
                  isPlatformView
                    ? { background: "var(--accent-color)", color: "#fff" }
                    : { background: "var(--ink)", color: "var(--bg)" }
                }
              >
                {isPlatformView ? <Shield size={16} aria-hidden /> : organizationInitials(label)}
              </span>
              <span className="min-w-0 flex-1">
                <span
                  className="block truncate text-[13.5px] font-semibold"
                  style={{ color: isPlatformView ? "var(--accent-ink)" : "var(--ink)" }}
                >
                  {label}
                </span>
                <span
                  className="block truncate text-[11.5px]"
                  style={{ color: isPlatformView ? "var(--accent-color)" : "var(--ink-3)" }}
                >
                  {isPlatformView ? "All organizations" : "Organization"}
                </span>
              </span>
              <ChevronsUpDown size={14} aria-hidden style={{ color: "var(--ink-4)" }} />
            </button>
          ) : (
            <button
              type="button"
              aria-label={`Switch organization. Current: ${label}`}
              title={label}
              className="grid h-10 w-10 place-items-center rounded-[11px] text-[12px] font-bold transition-colors hover:bg-white/10"
              style={
                isPlatformView
                  ? { background: "#4338ca", color: "#fff" }
                  : { border: "1px solid rgba(255,255,255,.2)", color: "#fbfaf8" }
              }
            >
              {isPlatformView ? <Shield size={18} aria-hidden /> : organizationInitials(label)}
            </button>
          )}
        </DropdownMenuTrigger>
        <DropdownMenuContent
          side={appearance === "tile" ? "right" : "bottom"}
          align="start"
          sideOffset={appearance === "tile" ? 10 : 6}
          className="w-64"
        >
          {organizations.length > 0 && <DropdownMenuLabel>Organizations</DropdownMenuLabel>}
          {organizations.map((org) => {
            const isSelected = !isPlatformView && org.id === selectedOrganization?.id;
            return (
              <DropdownMenuItem key={org.id} onSelect={() => selectOrganization(org)}>
                <Building2 aria-hidden />
                <span className="flex-1 truncate">{org.name}</span>
                {isSelected && <Check aria-label="Current" />}
              </DropdownMenuItem>
            );
          })}
          {isPlatformAdmin && (
            <>
              <DropdownMenuSeparator />
              <DropdownMenuItem onSelect={selectPlatform}>
                <Shield aria-hidden className="text-[#4338ca]" />
                <span className="flex-1">Platform admin</span>
                {isPlatformView && <Check aria-label="Current" />}
              </DropdownMenuItem>
            </>
          )}
          {/* The owner of a running trial creates no other organizations; the API refuses them. */}
          {canCreateOrganization && (
            <>
              <DropdownMenuSeparator />
              <DropdownMenuItem onSelect={() => setCreateOpen(true)}>
                <Plus aria-hidden />
                Create organization
              </DropdownMenuItem>
            </>
          )}
        </DropdownMenuContent>
      </DropdownMenu>
      <CreateOrganizationDialog open={createOpen} onOpenChange={setCreateOpen} />
    </>
  );
}
