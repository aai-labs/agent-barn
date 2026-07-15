"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useCurrentUser } from "@/auth/providers/user-context-provider";
import { useLogout } from "@/auth/hooks/use-logout";
import { PlusIcon, UserIcon, UsersIcon, BuildingIcon, LogOutIcon, ShieldIcon } from "@/components/icons";
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

  // Owners/admins (and superusers) manage members and see org spend; plain members can't.
  const { canManage: canManageMembers } = useActiveOrgRole();

  const navTabs = [
    { href: orgBase, label: "Home" },
    // Costs and the audit log are owner/admin-only (the endpoints are gated too); hide
    // them from members.
    ...(canManageMembers
      ? [
          { href: `${orgBase}/costs`, label: "Costs" },
          { href: `${orgBase}/audit-log`, label: "Audit log" },
        ]
      : []),
    { href: `${orgBase}/settings`, label: "Settings" },
  ];
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

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
      className="flex items-center gap-9 px-10 sticky top-0 z-10 h-[61px] flex-shrink-0"
      style={{ borderBottom: "1px solid var(--line)", background: "var(--bg)" }}
    >
      <div className="flex items-center gap-2.5 font-semibold text-[15.5px] tracking-tight" style={{ color: "var(--ink)" }}>
        <LogoMark size={26} />
        Agent Barn
      </div>

      <OrgSwitcher />

      <nav className="flex gap-0.5 flex-1">
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

      <div className="flex items-center gap-2.5">
        <button className="af-btn af-btn-primary" onClick={onHire}>
          <PlusIcon /> Hire agent
        </button>
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

              {user.isSuperuser && (
                <div style={{ borderTop: "1px solid var(--line)" }} className="py-1">
                  <div className="px-3.5 py-1 text-[11px] uppercase tracking-[0.08em] font-semibold" style={{ color: "var(--ink-5)" }}>
                    Super admin
                  </div>
                  <Link
                    href="/dashboard/users"
                    className="af-hover-bg w-full text-left flex items-center gap-2.5 px-3.5 py-2 text-[13.5px]"
                    style={{ color: "var(--ink-2)" }}
                    onClick={() => setMenuOpen(false)}
                  >
                    <UsersIcon /> Users
                  </Link>
                  <Link
                    href="/dashboard/organizations"
                    className="af-hover-bg w-full text-left flex items-center gap-2.5 px-3.5 py-2 text-[13.5px]"
                    style={{ color: "var(--ink-2)" }}
                    onClick={() => setMenuOpen(false)}
                  >
                    <BuildingIcon /> Organizations
                  </Link>
                  <Link
                    href="/dashboard/audit-logs"
                    className="af-hover-bg w-full text-left flex items-center gap-2.5 px-3.5 py-2 text-[13.5px]"
                    style={{ color: "var(--ink-2)" }}
                    onClick={() => setMenuOpen(false)}
                  >
                    <ShieldIcon /> Audit logs
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
      </div>
    </header>
  );
}

