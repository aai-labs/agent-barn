"use client";

import type { AgentAccessRoleRead } from "../schemas";
import { ShareRoleSelect } from "./share-role-select";

type ShareMemberRowMember = {
  email: string;
  fullName: string | null;
  isCreator: boolean;
};

function initialsOf(member: ShareMemberRowMember) {
  return (member.fullName ?? member.email)
    .split(" ")
    .map((w) => w[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
}

interface ShareMemberRowProps {
  member: ShareMemberRowMember;
  roleId: string;
  roles: AgentAccessRoleRead[];
  onChangeRole: (roleId: string) => void;
  onRemove: () => void;
  disabled: boolean;
}

export function ShareMemberRow({
  member,
  roleId,
  roles,
  onChangeRole,
  onRemove,
  disabled,
}: ShareMemberRowProps) {
  return (
    <div className="flex items-center gap-3 py-2.5">
      <div
        className="w-8 h-8 rounded-full grid place-items-center text-[11px] font-semibold text-white flex-shrink-0"
        style={{ background: "linear-gradient(135deg, #4338ca, #7c3aed)" }}
      >
        {initialsOf(member)}
      </div>
      <div className="min-w-0 flex-1">
        <div
          className="font-medium text-[13.5px] truncate"
          style={{ color: "var(--ink)" }}
        >
          {member.fullName || member.email}
          {member.isCreator && (
            <span
              className="ml-1.5 text-[11.5px] font-normal"
              style={{ color: "var(--ink-4)" }}
            >
              (creator)
            </span>
          )}
        </div>
        <div className="text-[12px] truncate" style={{ color: "var(--ink-3)" }}>
          {member.email}
        </div>
      </div>
      <ShareRoleSelect
        roles={roles}
        value={roleId}
        onChange={onChangeRole}
        onRemove={onRemove}
        disabled={disabled}
        ariaLabel={`Access role for ${member.email}`}
        className="w-32 shrink-0"
      />
    </div>
  );
}
