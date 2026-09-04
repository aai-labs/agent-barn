"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useCurrentUser } from "@/auth/providers/user-context-provider";
import { useLogout } from "@/auth/hooks/use-logout";
import { PlusIcon, UserIcon, UsersIcon, BuildingIcon, LogOutIcon, ShieldIcon, ServerIcon } from "@/components/icons";
import { FileText, Menu, Sparkles, X } from "lucide-react";
import { LogoMark } from "@/components/logo-mark";
import { OrgSwitcher } from "@/features/organizations/components/org-switcher";
import { useActiveOrgRole } from "@/features/organizations/hooks/use-active-org-role";
import { useOrganizationContext } from "@/features/organizations/providers/organization-provider";

interface TopNavProps {
  onHire: () => void;
}

export function TopNav({ onHire }: TopNavProps) {
  const pathname = usePathname();
  const router = useRouter();
  const { user } = useCurrentUser();
  const { selectedOrganization } = useOrganizationContext();
  const { logout, isLoggingOut } = useLogout();

  const orgId = selectedOrganization?.id;
  const orgBase = orgId ? `/dashboard/${orgId}` : "/dashboard";
  const isPlatformView = pathname?.startsWith("/dashboard/platform") ?? false;

  // Owners/admins (and platform admins) manage members and see org spend; plain members can't.
  const { canManage: canManageMembers } = useActiveOrgRole();

  const navTabs = isPlatformView
    ? [
        { href: "/dashboard/platform", label: "Overview" },
        { href: "/dashboard/platform/users", label: "Users" },
        { href: "/dashboard/platform/organizations", label: "Organizations" },
        { href: "/dashboard/platform/event-deliveries", label: "Event Deliveries" },
        { href: "/dashboard/platform/templates", label: "Templates" },
        { href: "/dashboard/platform/skills", label: "Skills" },
      ]
    : [
        { href: orgBase, label: "Home" },
        // Costs is owner/admin-only (the endpoint is gated too); hide it from members.
        ...(canManageMembers ? [{ href: `${orgBase}/costs`, label: "Costs" }] : []),
        { href: `${orgBase}/settings`, label: "Settings" },
      ];
  const [menuOpen, setMenuOpen] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setMobileOpen(false);
  }, [pathname]);

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const initials = (user.fullName ?? user.email ?? "U")
    .split(" ")
    .map((w) => w[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();

  const isActive = (href: string) => {
    // Home matches the org root and its agent pages; other tabs match their subtree.
    if (href === orgBase) {
      return pathname === orgBase || pathname.startsWith(`${orgBase}/agents`);
    }
    return pathname.startsWith(href);
  };

  return (
    <header
      className="sticky top-0 z-20 flex flex-col flex-shrink-0"
      style={{ borderBottom: "1px solid var(--line)", background: "var(--bg)" }}
    >
      <div className="flex items-center justify-between gap-3 px-4 md:gap-9 md:px-10 h-[61px] w-full">
        <div className="flex items-center gap-3 md:gap-9 min-w-0">
          <Link href="/" className="flex items-center gap-2.5 font-semibold text-[15.5px] tracking-tight flex-shrink-0" style={{ color: "var(--ink)" }}>
            <LogoMark size={26} />
            <span className="hidden sm:inline">Agent Barn</span>
          </Link>

          <OrgSwitcher />

          <nav className="hidden md:flex gap-0.5 flex-1">
            {navTabs.map(({ href, label }) => (
              <Link
                key={href}
                href={href}
                className="px-3.5 py-[7px] rounded-lg text-[14px] font-medium transition-colors"
                style={{
                  color: isActive(href) ? "var(--ink)" : "var(--ink-3)",
                  fontWeight: isActive(href) ? 600 : 500,
                  background: "transparent",
                }}
                onMouseEnter={(e) => {
                  if (!isActive(href))
                    (e.currentTarget as HTMLElement).style.background = "var(--bg-soft)";
                }}
                onMouseLeave={(e) => {
                  (e.currentTarget as HTMLElement).style.background = "transparent";
                }}
              >
                {label}
              </Link>
            ))}
          </nav>
        </div>

        <div className="flex items-center gap-2 md:gap-2.5 flex-shrink-0">
          {!isPlatformView && (
            <button className="af-btn af-btn-primary hidden sm:inline-flex" onClick={onHire}>
              <PlusIcon /> Hire agent
            </button>
          )}
          <div ref={menuRef} className="relative">
            <button
              className="w-[30px] h-[30px] rounded-full grid place-items-center text-[11.5px] font-semibold text-white flex-shrink-0"
              style={{ background: "linear-gradient(135deg, #4338ca, #7c3aed)" }}
              title={user.fullName ?? user.email}
              onClick={() => setMenuOpen((v) => !v)}
            >
              {initials}
            </button>

          {menuOpen && (
            <div
              className="absolute right-0 top-[calc(100%+8px)] w-56 rounded-xl py-1 z-50"
              style={{
                background: "var(--bg-elev)",
                border: "1px solid var(--line)",
                boxShadow: "var(--shadow-pop)",
              }}
            >
              <div className="px-3.5 py-2.5" style={{ borderBottom: "1px solid var(--line)" }}>
                <div className="font-medium text-[13.5px] truncate" style={{ color: "var(--ink)" }}>
                  {user.fullName ?? user.email}
                </div>
                <div className="text-[12px] truncate mt-0.5" style={{ color: "var(--ink-4)" }}>
                  {user.email}
                </div>
              </div>

              <div className="py-1">
                <Link
                  href="/dashboard/account"
                  className="af-hover-bg w-full text-left flex items-center gap-2.5 px-3.5 py-2 text-[13.5px]"
                  style={{ color: "var(--ink-2)" }}
                  onClick={() => setMenuOpen(false)}
                >
                  <UserIcon /> Account
                </Link>
                {canManageMembers && selectedOrganization && (
                  <Link
                    href={`${orgBase}/members`}
                    className="af-hover-bg w-full text-left flex items-center gap-2.5 px-3.5 py-2 text-[13.5px]"
                    style={{ color: "var(--ink-2)" }}
                    onClick={() => setMenuOpen(false)}
                  >
                    <BuildingIcon /> Manage organization
                  </Link>
                )}
              </div>

              {user.isPlatformAdmin && (
                <div style={{ borderTop: "1px solid var(--line)" }} className="py-1">
                  <div className="px-3.5 py-1 text-[11px] uppercase tracking-[0.08em] font-semibold" style={{ color: "var(--ink-5)" }}>
                    Platform
                  </div>
                  <Link
                    href="/dashboard/platform"
                    className="af-hover-bg w-full text-left flex items-center gap-2.5 px-3.5 py-2 text-[13.5px]"
                    style={{ color: "var(--ink-2)" }}
                    onClick={() => setMenuOpen(false)}
                  >
                    <ShieldIcon /> Platform view
                  </Link>
                  <Link
                    href="/dashboard/platform/users"
                    className="af-hover-bg w-full text-left flex items-center gap-2.5 px-3.5 py-2 text-[13.5px]"
                    style={{ color: "var(--ink-2)" }}
                    onClick={() => setMenuOpen(false)}
                  >
                    <UsersIcon /> Users
                  </Link>
                  <Link
                    href="/dashboard/platform/organizations"
                    className="af-hover-bg w-full text-left flex items-center gap-2.5 px-3.5 py-2 text-[13.5px]"
                    style={{ color: "var(--ink-2)" }}
                    onClick={() => setMenuOpen(false)}
                  >
                    <BuildingIcon /> Organizations
                  </Link>
                  <Link
                    href="/dashboard/platform/event-deliveries"
                    className="af-hover-bg w-full text-left flex items-center gap-2.5 px-3.5 py-2 text-[13.5px]"
                    style={{ color: "var(--ink-2)" }}
                    onClick={() => setMenuOpen(false)}
                  >
                    <ServerIcon /> Event Deliveries
                  </Link>
                  <Link
                    href="/dashboard/platform/templates"
                    className="af-hover-bg w-full text-left flex items-center gap-2.5 px-3.5 py-2 text-[13.5px]"
                    style={{ color: "var(--ink-2)" }}
                    onClick={() => setMenuOpen(false)}
                  >
                    <FileText size={14} /> Templates
                  </Link>
                  <Link
                    href="/dashboard/platform/skills"
                    className="af-hover-bg w-full text-left flex items-center gap-2.5 px-3.5 py-2 text-[13.5px]"
                    style={{ color: "var(--ink-2)" }}
                    onClick={() => setMenuOpen(false)}
                  >
                    <Sparkles size={14} /> Skills
                  </Link>
                </div>
              )}

              <div style={{ borderTop: "1px solid var(--line)" }} className="py-1">
                <button
                  className="af-hover-bg w-full text-left flex items-center gap-2.5 px-3.5 py-2 text-[13.5px]"
                  style={{ color: "var(--ink-2)" }}
                  disabled={isLoggingOut}
                  onClick={async () => {
                    setMenuOpen(false);
                    await logout();
                    router.push("/login");
                  }}
                >
                  <LogOutIcon /> {isLoggingOut ? "Logging out…" : "Log out"}
                </button>
              </div>
            </div>
          )}
        </div>

        <button
          type="button"
          className="md:hidden flex items-center justify-center p-1.5 rounded-lg transition-colors"
          style={{ color: "var(--ink-3)" }}
          aria-label={mobileOpen ? "Close navigation menu" : "Open navigation menu"}
          onClick={() => setMobileOpen((v) => !v)}
        >
          {mobileOpen ? <X size={20} /> : <Menu size={20} />}
        </button>
      </div>
    </div>

      {mobileOpen && (
        <nav
          className="md:hidden border-t px-4 py-3 space-y-1 w-full"
          style={{
            background: "var(--bg-elev)",
            borderColor: "var(--line)",
            boxShadow: "var(--shadow-pop)",
          }}
        >
          {!isPlatformView && (
            <div className="pb-2 sm:hidden">
              <button
                className="af-btn af-btn-primary w-full justify-center"
                onClick={() => {
                  setMobileOpen(false);
                  onHire();
                }}
              >
                <PlusIcon /> Hire agent
              </button>
            </div>
          )}
          {navTabs.map(({ href, label }) => (
            <Link
              key={href}
              href={href}
              className="block px-3 py-2 rounded-lg text-[14px] font-medium transition-colors"
              style={{
                color: isActive(href) ? "var(--ink)" : "var(--ink-3)",
                fontWeight: isActive(href) ? 600 : 500,
                background: isActive(href) ? "var(--bg-soft)" : "transparent",
              }}
              onClick={() => setMobileOpen(false)}
            >
              {label}
            </Link>
          ))}
        </nav>
      )}
    </header>
  );
}
