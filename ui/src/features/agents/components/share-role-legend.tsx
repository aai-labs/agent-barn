"use client";

import type { AgentAccessRoleRead } from "../schemas";
import { sensitiveWarningText, summarizeRolePermissions } from "../permissions";
import { formatRoleName } from "./share-role-select";

// Every role selector on this dialog shares this same catalogue, so the capability
// breakdown (and sensitive-permission callout) is shown once here instead of per
// dropdown option, where it made each row overflow.
export function ShareRoleLegend({ roles }: { roles: AgentAccessRoleRead[] }) {
  return (
    <div
      className="rounded-lg px-3.5 py-3 text-[12px] flex flex-col gap-1.5"
      style={{ background: "var(--bg-soft)", color: "var(--ink-3)" }}
    >
      {roles.map((role) => {
        const warning = sensitiveWarningText(role);
        return (
          <div key={role.id}>
            <span className="font-medium" style={{ color: "var(--ink-2)" }}>
              {formatRoleName(role.name)}
            </span>
            {" — "}
            {summarizeRolePermissions(role.permissions)}
            {warning && (
              <span style={{ color: "var(--warn)" }}> ({warning})</span>
            )}
          </div>
        );
      })}
    </div>
  );
}
