"use client";

import type { AgentAccessRoleRead } from "../schemas";

export function formatRoleName(name: string): string {
  return name === name.toUpperCase()
    ? name.charAt(0) + name.slice(1).toLowerCase()
    : name;
}

const REMOVE_VALUE = "__remove__";

interface ShareRoleSelectProps {
  roles: AgentAccessRoleRead[];
  value: string;
  onChange: (roleId: string) => void;
  /** When set, appends a "Remove access" option that calls this instead of onChange —
   * folds the two controls a member row needs (role, remove) into one compact dropdown
   * so the row never has to fit a full-width select next to a separate button. */
  onRemove?: () => void;
  disabled?: boolean;
  ariaLabel: string;
  className?: string;
}

// Capability details live once in <ShareRoleLegend>, not per option — every selector
// on this dialog shares the same role catalogue, so repeating the summary per option
// was both redundant and, with the sensitive-role warning, broke the row layout.
export function ShareRoleSelect({
  roles,
  value,
  onChange,
  onRemove,
  disabled,
  ariaLabel,
  className,
}: ShareRoleSelectProps) {
  // .af-select is `width: 100%` in globals.css — a plain size utility (e.g. w-32)
  // applied directly to the select ties with that rule and loses on cascade order.
  // Constraining this wrapper instead lets the 100% resolve against it correctly.
  return (
    <div className={className}>
      <select
        className="af-select"
        aria-label={ariaLabel}
        value={value}
        disabled={disabled}
        onChange={(e) => {
          if (e.target.value === REMOVE_VALUE) {
            onRemove?.();
            return;
          }
          onChange(e.target.value);
        }}
      >
        {roles.map((role) => (
          <option key={role.id} value={role.id}>
            {formatRoleName(role.name)}
          </option>
        ))}
        {onRemove && (
          <>
            <option disabled>─────────</option>
            <option value={REMOVE_VALUE}>Remove access</option>
          </>
        )}
      </select>
    </div>
  );
}
