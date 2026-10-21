"use client";

import { useState } from "react";
import type { ReactNode } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Building2, Check, Ellipsis, LogOut, Plus, Shield, User } from "lucide-react";

import { useLogout } from "@/auth/hooks/use-logout";
import { useCurrentUser } from "@/auth/providers/user-context-provider";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { CreateOrganizationDialog } from "@/features/organizations/components/create-organization-dialog";
import { useOrganizationSwitch } from "@/features/organizations/hooks/use-organization-switch";

import { useRailModel } from "../hooks/use-rail-model";
import { PLATFORM_RAIL_BACKGROUND, RAIL_BACKGROUND, type NavItem } from "../nav-model";
import { PanelLink } from "./context-panel";

const PRIMARY_COUNT = 3;

/**
 * The rail on a phone: its first destinations as a bottom bar, and the rest, with the
 * Organization switch, creating an Organization and the account, behind More.
 */
export function MobileBottomBar() {
  const rail = useRailModel();
  const [moreOpen, setMoreOpen] = useState(false);
  // Outside the sheet, which closes as the dialog opens.
  const [createOpen, setCreateOpen] = useState(false);
  const primary = rail.items.slice(0, PRIMARY_COUNT);
  const overflow = [...rail.items.slice(PRIMARY_COUNT), ...(rail.exit ? [rail.exit] : [])];
  const moreActive = overflow.some((item) => item.active);
  const idle = rail.tone === "platform" ? "text-[#b9b3f0]" : "text-[#a8a296]";

  return (
    <nav
      aria-label="Main"
      className="fixed inset-x-0 bottom-0 z-30 flex lg:hidden"
      style={{
        background: rail.tone === "platform" ? PLATFORM_RAIL_BACKGROUND : RAIL_BACKGROUND,
        paddingBottom: "env(safe-area-inset-bottom)",
      }}
    >
      {primary.map((item) => (
        <BarLink key={item.key} item={item} idle={idle} />
      ))}
      <Sheet open={moreOpen} onOpenChange={setMoreOpen}>
        <SheetTrigger asChild>
          <button
            type="button"
            className={`flex min-h-[60px] flex-1 flex-col items-center justify-center gap-0.5 text-[10.5px] font-medium ${moreActive ? "text-white" : idle}`}
          >
            <Ellipsis size={20} aria-hidden />
            More
          </button>
        </SheetTrigger>
        <SheetContent side="bottom" className="max-h-[85vh] gap-0 overflow-y-auto rounded-t-[20px] px-3 pb-6 pt-5">
          <SheetHeader className="sr-only">
            <SheetTitle>More</SheetTitle>
          </SheetHeader>
          <MoreSheetBody
            overflow={overflow}
            onNavigate={() => setMoreOpen(false)}
            onCreateOrganization={() => {
              setMoreOpen(false);
              setCreateOpen(true);
            }}
          />
        </SheetContent>
      </Sheet>
      <CreateOrganizationDialog open={createOpen} onOpenChange={setCreateOpen} />
    </nav>
  );
}

function BarLink({ item, idle }: { item: NavItem; idle: string }) {
  const Icon = item.icon;
  return (
    <Link
      href={item.href}
      aria-current={item.active ? "page" : undefined}
      className={`flex min-h-[60px] min-w-0 flex-1 flex-col items-center justify-center gap-0.5 px-1 text-[10.5px] font-medium ${item.active ? "text-white" : idle}`}
    >
      <Icon size={20} aria-hidden />
      <span className="max-w-full truncate">{item.label}</span>
    </Link>
  );
}

function MoreSheetBody({
  overflow,
  onNavigate,
  onCreateOrganization,
}: {
  overflow: NavItem[];
  onNavigate: () => void;
  onCreateOrganization: () => void;
}) {
  const router = useRouter();
  const { user } = useCurrentUser();
  const { logout, isLoggingOut } = useLogout();
  const { organizations, selectedOrganization, isPlatformView, selectOrganization, canCreateOrganization } =
    useOrganizationSwitch();

  return (
    <div className="flex flex-col gap-4 [&_a]:min-h-11">
      {overflow.length > 0 && (
        <SheetSection label="Go to">
          {overflow.map((item) => (
            <PanelLink key={item.key} item={item} onNavigate={onNavigate} />
          ))}
        </SheetSection>
      )}

      {/* The switch only when there is somewhere to switch to; creating one at every count,
          as the desktop switcher offers it. */}
      {(organizations.length > 1 || canCreateOrganization) && (
        <SheetSection label="Organizations">
          {organizations.length > 1 && organizations.map((org) => {
            const isSelected = !isPlatformView && org.id === selectedOrganization?.id;
            return (
              <button
                key={org.id}
                type="button"
                className="af-hover-bg flex min-h-11 items-center gap-2.5 rounded-lg px-2.5 text-left text-[13.5px]"
                style={{ color: "var(--ink-2)", fontWeight: isSelected ? 600 : 500 }}
                onClick={() => {
                  onNavigate();
                  selectOrganization(org);
                }}
              >
                <Building2 size={16} aria-hidden style={{ color: "var(--ink-3)" }} />
                <span className="flex-1 truncate">{org.name}</span>
                {isSelected && <Check size={16} aria-label="Current" />}
              </button>
            );
          })}
          {canCreateOrganization && (
            <button
              type="button"
              className="af-hover-bg flex min-h-11 items-center gap-2.5 rounded-lg px-2.5 text-left text-[13.5px] font-medium"
              style={{ color: "var(--ink-2)" }}
              onClick={onCreateOrganization}
            >
              <Plus size={16} aria-hidden style={{ color: "var(--ink-3)" }} />
              Create organization
            </button>
          )}
        </SheetSection>
      )}

      <SheetSection label={user.fullName ?? user.email}>
        <Link
          href="/dashboard/account"
          onClick={onNavigate}
          className="af-hover-bg flex items-center gap-2.5 rounded-lg px-2.5 text-[13.5px] font-medium"
          style={{ color: "var(--ink-2)" }}
        >
          <User size={16} aria-hidden style={{ color: "var(--ink-3)" }} /> Account
        </Link>
        {user.isPlatformAdmin && !overflow.some((item) => item.key === "exit") && (
          <Link
            href="/dashboard/platform"
            onClick={onNavigate}
            className="af-hover-bg flex items-center gap-2.5 rounded-lg px-2.5 text-[13.5px] font-medium"
            style={{ color: "var(--ink-2)" }}
          >
            <Shield size={16} aria-hidden style={{ color: "var(--ink-3)" }} /> Platform admin
          </Link>
        )}
        <button
          type="button"
          disabled={isLoggingOut}
          className="af-hover-bg flex min-h-11 items-center gap-2.5 rounded-lg px-2.5 text-left text-[13.5px] font-medium"
          style={{ color: "var(--ink-2)" }}
          onClick={async () => {
            onNavigate();
            await logout();
            router.push("/login");
          }}
        >
          <LogOut size={16} aria-hidden style={{ color: "var(--ink-3)" }} />
          {isLoggingOut ? "Logging out…" : "Log out"}
        </button>
      </SheetSection>
    </div>
  );
}

function SheetSection({ label, children }: { label: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-px">
      <div
        className="truncate px-2.5 pb-1 text-[10.5px] font-semibold uppercase tracking-[0.09em]"
        style={{ color: "var(--ink-4)" }}
      >
        {label}
      </div>
      {children}
    </section>
  );
}
