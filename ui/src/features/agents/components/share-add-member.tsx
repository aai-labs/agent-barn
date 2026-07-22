"use client";

import { useState } from "react";
import { Loader2 } from "lucide-react";

import { SearchInput } from "@/components/search-input";

import { useEligibleAgentAccess } from "../hooks/use-eligible-agent-access";
import type { AgentAccessCandidateRead, AgentAccessRoleRead } from "../schemas";
import { defaultRoleId } from "../permissions";
import { ShareRoleSelect } from "./share-role-select";

function ShareCandidateRow({
  candidate,
  roles,
  onGrant,
  disabled,
}: {
  candidate: AgentAccessCandidateRead;
  roles: AgentAccessRoleRead[];
  onGrant: (candidate: AgentAccessCandidateRead, roleId: string) => void;
  disabled: boolean;
}) {
  const [roleId, setRoleId] = useState(() => defaultRoleId(roles) ?? "");

  return (
    <div className="flex items-center gap-3 py-2.5">
      <div className="min-w-0 flex-1">
        <div className="font-medium text-[13.5px] truncate" style={{ color: "var(--ink)" }}>
          {candidate.fullName || candidate.email}
        </div>
        <div className="text-[12px] truncate" style={{ color: "var(--ink-3)" }}>
          {candidate.email}
        </div>
      </div>
      <ShareRoleSelect
        roles={roles}
        value={roleId}
        onChange={setRoleId}
        disabled={disabled}
        ariaLabel={`Access role for ${candidate.email}`}
        className="w-56 flex-shrink-0"
      />
      <button
        className="af-btn flex-shrink-0"
        aria-label={`Add ${candidate.email}`}
        disabled={!roleId || disabled}
        onClick={() => onGrant(candidate, roleId)}
      >
        Add
      </button>
    </div>
  );
}

interface ShareAddMemberProps {
  agentId: string;
  roles: AgentAccessRoleRead[];
  onGrant: (candidate: AgentAccessCandidateRead, roleId: string) => void;
  disabled: boolean;
  isOpen: boolean;
  /** Already-staged rows (existing or newly added this session) — hidden from search. */
  excludeUserIds: string[];
  /**
   * Members staged for removal this session. The server still considers them assigned
   * (nothing's saved yet), so the eligible-access search won't return them — merge them
   * in here, client-side, so searching for someone you just unstaged still finds them.
   */
  localCandidates: AgentAccessCandidateRead[];
}

export function ShareAddMember({
  agentId,
  roles,
  onGrant,
  disabled,
  isOpen,
  excludeUserIds,
  localCandidates,
}: ShareAddMemberProps) {
  const [search, setSearch] = useState("");
  const term = search.trim();
  const { candidates: allCandidates, isLoading } = useEligibleAgentAccess(
    agentId,
    term,
    isOpen && term.length > 0,
  );
  const excluded = new Set(excludeUserIds);
  const termLower = term.toLowerCase();
  const matchingLocal = localCandidates.filter(
    (c) =>
      !excluded.has(c.userId) &&
      ((c.fullName ?? "").toLowerCase().includes(termLower) ||
        c.email.toLowerCase().includes(termLower)),
  );
  const candidates = [
    ...matchingLocal,
    ...allCandidates.filter(
      (c) => !excluded.has(c.userId) && !matchingLocal.some((m) => m.userId === c.userId),
    ),
  ];

  return (
    <div>
      <SearchInput
        onSearch={setSearch}
        placeholder="Search Members by name or email"
        ariaLabel="Search Members to grant access"
      />
      {term.length === 0 ? (
        <p className="mt-2 text-[12.5px]" style={{ color: "var(--ink-4)" }}>
          Search for an accepted Member to grant them direct access.
        </p>
      ) : isLoading ? (
        <div
          className="flex items-center gap-2 mt-2 text-[12.5px]"
          style={{ color: "var(--ink-3)" }}
        >
          <Loader2 width={13} height={13} className="animate-spin" /> Searching…
        </div>
      ) : candidates.length === 0 ? (
        <p className="mt-2 text-[12.5px]" style={{ color: "var(--ink-4)" }}>
          No matching Members found.
        </p>
      ) : (
        <div className="mt-1 divide-y" style={{ borderColor: "var(--line)" }}>
          {candidates.map((candidate) => (
            <ShareCandidateRow
              key={candidate.userId}
              candidate={candidate}
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
