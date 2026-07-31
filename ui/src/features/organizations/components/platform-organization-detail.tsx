"use client";

import { useState, type ReactNode } from "react";
import Link from "next/link";
import {
  Building,
  CalendarDays,
  ChevronLeft,
  Loader2,
  UserRound,
  Users,
} from "lucide-react";

import { AppErrorState } from "@/components/app-error-state";
import { SearchInput } from "@/components/search-input";

import { usePlatformOrganization } from "../hooks/use-platform-organization";
import { usePlatformOrganizationMembers } from "../hooks/use-platform-organization-members";
import type { PlatformOrganizationMember } from "../schemas";

function orgInitials(name: string) {
  const letters = name
    .split(/\s+/)
    .filter(Boolean)
    .map((w) => w[0])
    .join("");
  return (letters || name).slice(0, 2).toUpperCase();
}

function initialsOf(member: PlatformOrganizationMember) {
  return (member.fullName ?? member.email)
    .split(" ")
    .map((w) => w[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
}

function StatTile({
  icon,
  label,
  children,
}: {
  icon: ReactNode;
  label: string;
  children: ReactNode;
}) {
  return (
    <div className="af-card px-4 py-3.5">
      <div
        className="text-[11px] font-semibold uppercase tracking-[0.06em] mb-1.5"
        style={{ color: "var(--ink-5)" }}
      >
        {label}
      </div>
      <div
        className="flex items-center gap-2 text-[13.5px] min-w-0"
        style={{ color: "var(--ink)" }}
      >
        <span style={{ color: "var(--ink-4)", flexShrink: 0 }}>{icon}</span>
        <span className="min-w-0 truncate">{children}</span>
      </div>
    </div>
  );
}

const ROLE_LABEL: Record<string, string> = {
  OWNER: "Owner",
  ADMIN: "Admin",
  MEMBER: "Member",
};

export function PlatformOrganizationDetail({ organizationId }: { organizationId: string }) {
  const [search, setSearch] = useState("");
  const { organization, isLoading, error, refetch } = usePlatformOrganization(organizationId);
  const {
    members,
    total: memberTotal,
    hasNextPage,
    fetchNextPage,
    isFetchingNextPage,
    isLoading: membersLoading,
    error: membersError,
    refetch: refetchMembers,
  } = usePlatformOrganizationMembers(organizationId, { search });

  if (isLoading) {
    return (
      <div className="af-page">
        <div
          className="flex items-center gap-2 py-10 text-[13.5px]"
          style={{ color: "var(--ink-3)" }}
        >
          <Loader2 width={15} height={15} className="animate-spin" /> Loading organization…
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="af-page">
        <AppErrorState
          error={error}
          title="We couldn't load this organization"
          description="The organization detail is unavailable right now."
          onRetry={() => { void refetch(); }}
          retryLabel="Retry"
          className="min-h-[240px] p-0"
        />
      </div>
    );
  }

  if (!organization) {
    return (
      <div className="af-page">
        <div className="text-[14px]" style={{ color: "var(--ink-3)" }}>
          Organization not found.
        </div>
      </div>
    );
  }

  return (
    <div className="af-page">
      <Link
        href="/dashboard/platform/organizations"
        className="inline-flex items-center gap-1 text-[13px] mb-4"
        style={{ color: "var(--ink-3)" }}
      >
        <ChevronLeft width={14} height={14} /> Organizations
      </Link>

      <div className="flex items-start gap-4 mb-7">
        <div
          className="grid h-14 w-14 flex-shrink-0 place-items-center rounded-2xl text-[18px] font-semibold text-white"
          style={{ background: "linear-gradient(135deg, #4338ca, #7c3aed)" }}
          aria-hidden
        >
          {orgInitials(organization.name)}
        </div>

        <div className="min-w-0 flex-1 pt-0.5">
          <h1
            className="m-0 truncate text-[26px] font-semibold tracking-tight"
            style={{ color: "var(--ink)" }}
          >
            {organization.name}
          </h1>
          <p className="m-0 mt-1 text-[14px]" style={{ color: "var(--ink-3)" }}>
            {organization.description || "No description"}
          </p>
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4 mb-9">
        <StatTile icon={<Users width={14} height={14} />} label="Members">
          {membersLoading ? "—" : `${memberTotal} ${memberTotal === 1 ? "member" : "members"}`}
        </StatTile>
        <StatTile icon={<UserRound width={14} height={14} />} label="Owner">
          <span title={organization.ownerEmail ?? undefined}>
            {organization.ownerName || organization.ownerEmail || "No owner"}
          </span>
        </StatTile>
        <StatTile icon={<Building width={14} height={14} />} label="Creator">
          <span title={organization.creatorEmail ?? undefined}>
            {organization.creatorName || organization.creatorEmail || "Unknown"}
          </span>
        </StatTile>
        <StatTile icon={<CalendarDays width={14} height={14} />} label="Created">
          {new Date(organization.createdAt).toLocaleDateString(undefined, {
            year: "numeric",
            month: "short",
            day: "numeric",
          })}
        </StatTile>
      </div>

      <div style={{ borderTop: "1px solid var(--line)" }} className="pt-8">
        <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between mb-4">
          <div>
            <h2 className="text-[16px] font-semibold m-0" style={{ color: "var(--ink)" }}>
              Members
            </h2>
            <p className="text-[13px] m-0 mt-0.5" style={{ color: "var(--ink-4)" }}>
              {memberTotal} {memberTotal === 1 ? "member" : "members"}
            </p>
          </div>
          <SearchInput
            onSearch={setSearch}
            placeholder="Search by name or email"
            ariaLabel="Search members"
            className="w-full md:w-64"
          />
        </div>

        {membersLoading ? (
          <div className="flex items-center gap-2 py-10 text-[13.5px]" style={{ color: "var(--ink-3)" }}>
            <Loader2 width={15} height={15} className="animate-spin" /> Loading members…
          </div>
        ) : membersError ? (
          <AppErrorState
            error={membersError}
            title="We couldn't load members"
            description="The members list is unavailable right now."
            onRetry={() => { void refetchMembers(); }}
            retryLabel="Retry members"
            className="min-h-[240px] p-0"
          />
        ) : members.length === 0 ? (
          <div
            className="flex items-center justify-center text-center py-10 rounded-2xl text-[13.5px]"
            style={{ border: "1px dashed var(--line-strong)", color: "var(--ink-3)" }}
          >
            No members found.
          </div>
        ) : (
          <div className="flex flex-col gap-2.5">
            {members.map((member) => (
              <div
                key={member.userId}
                className="af-card flex items-center gap-4 px-5 py-3.5"
              >
                <div
                  className="w-9 h-9 rounded-full grid place-items-center text-[12px] font-semibold text-white flex-shrink-0"
                  style={{ background: "linear-gradient(135deg, #4338ca, #7c3aed)" }}
                >
                  {initialsOf(member)}
                </div>

                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="font-medium text-[14px] truncate" style={{ color: "var(--ink)" }}>
                      {member.fullName || member.email}
                    </span>
                    {member.isPending && (
                      <span
                        className="text-[11px] px-1.5 py-0.5 rounded-md font-medium"
                        style={{ background: "var(--warn-soft)", color: "var(--warn)" }}
                      >
                        Pending
                      </span>
                    )}
                  </div>
                  <div className="text-[12.5px] truncate" style={{ color: "var(--ink-3)" }}>
                    {member.email}
                  </div>
                </div>

                <span
                  className="flex-shrink-0 rounded-full px-2.5 py-1 text-[12px] font-medium"
                  style={{ background: "var(--bg-soft)", color: "var(--ink-3)", border: "1px solid var(--line)" }}
                >
                  {ROLE_LABEL[member.role] ?? member.role}
                </span>
              </div>
            ))}
          </div>
        )}

        {hasNextPage && (
          <div className="flex justify-center mt-6">
            <button className="af-btn" onClick={() => fetchNextPage()} disabled={isFetchingNextPage}>
              {isFetchingNextPage
                ? <><Loader2 width={14} height={14} className="animate-spin" /> Loading more</>
                : "Load more members"}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
