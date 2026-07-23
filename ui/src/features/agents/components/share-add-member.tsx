"use client";

import { useState } from "react";
import { Loader2 } from "lucide-react";

import { SearchInput } from "@/components/search-input";
import type { OrganizationMember } from "@/features/organizations/schemas";

import { useOrganizationMemberSearch } from "../hooks/use-organization-member-search";
import type { AgentAccessRoleRead } from "../schemas";
import { defaultRoleId } from "../permissions";
import { formatRoleName, ShareRoleSelect } from "./share-role-select";

type RowStatus =
  | { kind: "addable" }
  | { kind: "already-has-access" }
  | { kind: "implicit-owner" }
  | { kind: "pending" };

function statusFor(
  member: OrganizationMember,
  assignedUserIds: Set<string>,
): RowStatus {
  if (assignedUserIds.has(member.userId)) return { kind: "already-has-access" };
  if (member.role === "OWNER" || member.role === "ADMIN") {
    return { kind: "implicit-owner" };
  }
  if (member.isPending) return { kind: "pending" };
  return { kind: "addable" };
}

function ShareCandidateRow({
  member,
  status,
  roles,
  onGrant,
  disabled,
}: {
  member: OrganizationMember;
  status: RowStatus;
  roles: AgentAccessRoleRead[];
  onGrant: (member: OrganizationMember, roleId: string) => void;
  disabled: boolean;
}) {
  const [roleId, setRoleId] = useState(() => defaultRoleId(roles) ?? "");
  const addable = status.kind === "addable";

  return (
    <div className="flex items-center gap-3 py-2.5">
      <div className="min-w-0 flex-1">
        <div className="font-medium text-[13.5px] truncate" style={{ color: "var(--ink)" }}>
          {member.fullName || member.email}
        </div>
        <div className="text-[12px] truncate" style={{ color: "var(--ink-3)" }}>
          {member.email}
        </div>
      </div>
      {status.kind === "already-has-access" && (
        <span className="text-[12px] flex-shrink-0" style={{ color: "var(--ink-4)" }}>
          Already has access
        </span>
      )}
      {status.kind === "implicit-owner" && (
        <span className="text-[12px] flex-shrink-0" style={{ color: "var(--ink-4)" }}>
          {formatRoleName(member.role)} — full access already
        </span>
      )}
      {status.kind === "pending" && (
        <span className="text-[12px] flex-shrink-0" style={{ color: "var(--ink-4)" }}>
          Pending invite
        </span>
      )}
      {addable && (
        <>
          <ShareRoleSelect
            roles={roles}
            value={roleId}
            onChange={setRoleId}
            disabled={disabled}
            ariaLabel={`Access role for ${member.email}`}
            className="w-32 flex-shrink-0"
          />
          <button
            className="af-btn flex-shrink-0"
            aria-label={`Add ${member.email}`}
            disabled={!roleId || disabled}
            onClick={() => onGrant(member, roleId)}
          >
            Add
          </button>
        </>
      )}
    </div>
  );
}

interface ShareAddMemberProps {
  organizationId: string;
  roles: AgentAccessRoleRead[];
  onGrant: (member: OrganizationMember, roleId: string) => void;
  disabled: boolean;
  isOpen: boolean;
  /** Local draft's currently-assigned user ids — drives the "already has access" state
   * so search results reflect the in-progress edit, not just the last-saved snapshot. */
  assignedUserIds: string[];
}

export function ShareAddMember({
  organizationId,
  roles,
  onGrant,
  disabled,
  isOpen,
  assignedUserIds,
}: ShareAddMemberProps) {
  const [search, setSearch] = useState("");
  const term = search.trim();
  const { members: results, isLoading } = useOrganizationMemberSearch(
    organizationId,
    term,
    isOpen && term.length > 0,
  );
  const assigned = new Set(assignedUserIds);

  return (
    <div>
      <SearchInput
        onSearch={setSearch}
        placeholder="Search Members by name or email"
        ariaLabel="Search Members to grant access"
      />
      {term.length === 0 ? (
        <p className="mt-2 text-[12.5px]" style={{ color: "var(--ink-4)" }}>
          Search for a Member to grant them direct access.
        </p>
      ) : isLoading ? (
        <div
          className="flex items-center gap-2 mt-2 text-[12.5px]"
          style={{ color: "var(--ink-3)" }}
        >
          <Loader2 width={13} height={13} className="animate-spin" /> Searching…
        </div>
      ) : results.length === 0 ? (
        <p className="mt-2 text-[12.5px]" style={{ color: "var(--ink-4)" }}>
          No matching Members found.
        </p>
      ) : (
        <div className="mt-1 divide-y" style={{ borderColor: "var(--line)" }}>
          {results.map((member) => (
            <ShareCandidateRow
              key={member.userId}
              member={member}
              status={statusFor(member, assigned)}
              roles={roles}
              onGrant={onGrant}
              disabled={disabled}
            />
          ))}
        </div>
      )}
    </div>
  );
}
