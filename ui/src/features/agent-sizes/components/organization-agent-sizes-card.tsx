"use client";

import { useState } from "react";

import { Checkbox } from "@/components/ui/checkbox";
import type { PlatformOrganization } from "@/features/organizations/schemas";
import { getErrorDisplay } from "@/shared/api/error/get-error-display";

import { useAgentSizes } from "../hooks/use-agent-sizes";
import { useSetOrganizationAgentSizes } from "../hooks/use-organization-agent-sizes";
import { agentCountLabel, describeSize } from "../utils";

type Draft = { canChoose: boolean; sizeIds: string[] };

function sameIds(a: string[], b: string[]) {
  return a.length === b.length && a.every((id) => b.includes(id));
}

/**
 * Platform → Organization → Agent sizes: whether this Organization's Owners and Admins may
 * choose CPU and memory for its Agents, and from which sizes. The default is always available
 * and is never listed; withdrawing a size leaves the Agents already on it where they are, which
 * the card says before it saves.
 */
export function OrganizationAgentSizesCard({ organization }: { organization: PlatformOrganization }) {
  const { sizes, isLoadingSizes, sizesError } = useAgentSizes(organization.id);
  const setAllowed = useSetOrganizationAgentSizes(organization.id);
  const saved = organization.agentSizeIds;
  const [draft, setDraft] = useState<Draft | null>(null);
  const current = draft ?? { canChoose: saved.length > 0, sizeIds: saved };

  const defaultSize = sizes.find((size) => size.isDefault);
  // Enabled sizes can be offered; a disabled one stays listed only while it is still allowed.
  const options = sizes.filter((size) => !size.isDefault && (size.enabled || saved.includes(size.id)));
  const willSave = current.canChoose ? current.sizeIds : [];
  const dirty = !sameIds(willSave, saved) || current.canChoose !== saved.length > 0;
  const missingChoice = current.canChoose && current.sizeIds.length === 0;
  const keptOn = sizes.filter((size) => saved.includes(size.id) && !willSave.includes(size.id) && size.agentCount > 0);

  const update = (next: Partial<Draft>) => {
    setAllowed.reset();
    setDraft({ ...current, ...next });
  };
  const toggleSize = (id: string, checked: boolean) =>
    update({ sizeIds: checked ? [...current.sizeIds, id] : current.sizeIds.filter((sizeId) => sizeId !== id) });
  const save = () => setAllowed.mutate(willSave, { onSuccess: () => setDraft(null) });

  return (
    <section className="af-card mb-9 p-5" aria-label="Agent specs">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0 flex-1 basis-[22rem]">
          <h2 className="m-0 text-[15px] font-semibold" style={{ color: "var(--ink)" }}>
            Agent specs
          </h2>
          <p className="mb-0 mt-1 text-[13.5px] leading-relaxed" style={{ color: "var(--ink-3)" }}>
            {defaultSize ? `Every agent runs on ${defaultSize.name}, the default, ` : "Every agent runs on the default spec "}
            unless this organization may choose. Its owners and admins then pick from the specs below, and a change
            applies the next time the agent starts.
          </p>
        </div>
        <label className="flex items-center gap-2.5 text-[13.5px] font-medium" style={{ color: "var(--ink)" }}>
          <button
            type="button"
            role="switch"
            aria-checked={current.canChoose}
            aria-label="Can choose an Agent spec"
            disabled={isLoadingSizes || setAllowed.isPending || (options.length === 0 && !current.canChoose)}
            onClick={() => update({ canChoose: !current.canChoose })}
            className="relative h-5 w-9 shrink-0 rounded-full transition-colors disabled:cursor-not-allowed disabled:opacity-50"
            style={{ backgroundColor: current.canChoose ? "var(--ink)" : "var(--line)" }}
          >
            <span
              className={`absolute top-0.5 left-0.5 h-4 w-4 rounded-full bg-white transition-transform ${current.canChoose ? "translate-x-4" : ""}`}
            />
          </button>
          Can choose an Agent spec
        </label>
      </div>

      {isLoadingSizes && (
        <p className="mb-0 mt-4 text-[13px]" style={{ color: "var(--ink-3)" }}>
          Loading specs…
        </p>
      )}
      {sizesError && (
        <p className="mb-0 mt-4 text-[13px]" role="alert" style={{ color: "var(--err)" }}>
          {getErrorDisplay(sizesError).description}
        </p>
      )}
      {!isLoadingSizes && !sizesError && options.length === 0 && (
        <p className="mb-0 mt-4 text-[13px]" style={{ color: "var(--ink-3)" }}>
          There are no specs besides the default to offer. Add one under Platform settings → Agent specs.
        </p>
      )}

      {current.canChoose && options.length > 0 && (
        <fieldset className="mt-4 flex flex-col gap-2.5 border-0 p-0">
          <legend className="mb-2 text-[13px] font-medium" style={{ color: "var(--ink-2)" }}>
            Specs it may choose besides {defaultSize?.name ?? "the default"}
          </legend>
          {options.map((size) => {
            const checked = current.sizeIds.includes(size.id);
            return (
              <label
                key={size.id}
                className="flex items-center gap-2.5 text-[13.5px]"
                style={{ color: size.enabled ? "var(--ink)" : "var(--ink-3)" }}
              >
                <Checkbox
                  checked={checked}
                  // A disabled size can be withdrawn but not offered again.
                  disabled={setAllowed.isPending || (!size.enabled && !checked)}
                  onCheckedChange={(value) => toggleSize(size.id, value === true)}
                  aria-label={size.name}
                />
                {describeSize(size)}
                {!size.enabled && <span className="text-[12px]">(disabled: agents on it keep it)</span>}
              </label>
            );
          })}
        </fieldset>
      )}

      {setAllowed.isError && (
        <p className="mb-0 mt-3 text-[13px]" role="alert" style={{ color: "var(--err)" }}>
          {getErrorDisplay(setAllowed.error).description}
        </p>
      )}

      {dirty && keptOn.length > 0 && (
        <p className="mb-0 mt-4 text-[13px]" data-testid="agent-sizes-withdraw-note" style={{ color: "var(--ink-3)" }}>
          {keptOn.map((size) => `${agentCountLabel(size.agentCount)} on ${size.name}`).join(", ")} stay on{" "}
          {keptOn.length === 1 ? "it" : "them"} until someone changes their spec. Withdrawing only stops a spec
          being chosen again.
        </p>
      )}

      {dirty && (
        <div className="mt-4 flex flex-wrap items-center justify-end gap-2">
          {missingChoice && (
            <span className="mr-auto text-[13px]" style={{ color: "var(--ink-3)" }}>
              Choose at least one spec, or turn choosing off.
            </span>
          )}
          <button
            type="button"
            className="af-btn af-btn-sm"
            disabled={setAllowed.isPending}
            onClick={() => {
              setAllowed.reset();
              setDraft(null);
            }}
          >
            Cancel
          </button>
          <button
            type="button"
            className="af-btn af-btn-sm af-btn-primary"
            disabled={setAllowed.isPending || missingChoice}
            onClick={save}
          >
            {setAllowed.isPending ? "Saving…" : "Save"}
          </button>
        </div>
      )}
    </section>
  );
}
