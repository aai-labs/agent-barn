"use client";

import { useId, useState } from "react";

import { ConfirmationDialog } from "@/components/confirmation-dialog";
import { getErrorDisplay } from "@/shared/api/error/get-error-display";

import { useSetAgentLimit } from "../hooks/use-set-agent-limit";
import type { PlatformOrganization } from "../schemas";

function describe(limit: number | null | undefined) {
  if (limit == null) return "No limit";
  return `${limit} ${limit === 1 ? "agent" : "agents"}`;
}

/** Empty for "use the default", NaN for anything that is not a whole number of zero or more. */
function parseLimit(raw: string): number | null {
  const trimmed = raw.trim();
  if (trimmed === "") return null;
  return /^\d+$/.test(trimmed) ? Number(trimmed) : Number.NaN;
}

/** How many agents an organization may run, and the Platform Administrator's way to change it. */
export function AgentLimitCard({ organization }: { organization: PlatformOrganization }) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState("");
  const inputId = useId();
  const hintId = `${inputId}-hint`;
  const errorId = `${inputId}-error`;
  const setLimit = useSetAgentLimit(organization.id);

  const parsed = parseLimit(value);
  const invalid = Number.isNaN(parsed);
  const own = organization.agentLimit ?? null;

  return (
    <section className="af-card mb-9 p-5" aria-label="Agents">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          <h2 className="m-0 text-[15px] font-semibold" style={{ color: "var(--ink)" }}>
            Agents
          </h2>
          <p className="mb-0 mt-1 text-[13.5px] leading-relaxed" style={{ color: "var(--ink-3)" }}>
            {describe(organization.agentLimitInForce)} · {own == null ? "The default" : "Set for this organization"}
          </p>
        </div>
        <button
          type="button"
          className="af-btn"
          onClick={() => {
            setValue(own == null ? "" : String(own));
            setLimit.reset();
            setEditing(true);
          }}
        >
          Change
        </button>
      </div>
      <ConfirmationDialog
        open={editing}
        onOpenChange={setEditing}
        title={`How many agents may ${organization.name} run?`}
        description="Agents it already runs are kept; a lower limit only stops new hires."
        confirmLabel="Save"
        pendingLabel="Saving…"
        isPending={setLimit.isPending}
        confirmDisabled={invalid}
        onConfirm={async () => {
          if (invalid) return;
          try {
            await setLimit.mutateAsync(parsed);
            setEditing(false);
          } catch {
            /* The error stays in the dialog. */
          }
        }}
      >
        <div className="flex flex-col gap-1.5">
          <label htmlFor={inputId} className="text-[0.84rem] font-medium" style={{ color: "var(--ink)" }}>
            Agents it may run
          </label>
          <div className="flex flex-wrap items-center gap-3">
            <input
              id={inputId}
              className="af-input"
              style={{ width: 120 }}
              inputMode="numeric"
              value={value}
              aria-invalid={invalid ? true : undefined}
              aria-describedby={invalid ? `${hintId} ${errorId}` : hintId}
              onChange={(event) => setValue(event.target.value)}
            />
            {value.trim() !== "" && (
              <button
                type="button"
                className="text-[0.84rem] underline underline-offset-2"
                style={{ color: "var(--ink-2)" }}
                onClick={() => setValue("")}
              >
                Use the default
              </button>
            )}
          </div>
          <p id={hintId} className="m-0 text-[0.8rem]" style={{ color: "var(--ink-3)" }}>
            Leave empty to use the default for {organization.isTrial ? "trials" : "organizations"}.
          </p>
          {invalid && (
            <p id={errorId} className="m-0 text-[0.8rem]" role="alert" style={{ color: "var(--err)" }}>
              Enter a whole number of zero or more.
            </p>
          )}
        </div>
        {setLimit.isError && (
          <p className="mb-0 mt-3 text-[13px]" role="alert" style={{ color: "var(--err)" }}>
            {getErrorDisplay(setLimit.error).description}
          </p>
        )}
      </ConfirmationDialog>
    </section>
  );
}
