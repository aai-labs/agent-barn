"use client";

import { useState } from "react";
import { MoreHorizontal, Plus } from "lucide-react";

import { AppErrorState } from "@/components/app-error-state";
import { ConfirmationDialog } from "@/components/confirmation-dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { toastError } from "@/shared/toast";

import { useTierActions, useTiers } from "../hooks/use-tiers";
import type { Tier } from "../schemas";
import { ACTIVATION_LABELS, describeFeatures, describePlatforms, describePrice, describeUsage } from "../utils";
import { TierDialog } from "./tier-dialog";

/**
 * Platform → Settings → Tiers: what organizations may use and what they pay for it.
 *
 * Free and none are the system's own and are never deleted; none never changes. A tier's key
 * and how it is activated are set when it is added. Turning a tier off stops it being offered;
 * it moves nobody already on it.
 */
export function TiersSettings() {
  const { tiers, isLoadingTiers, tiersError, reloadTiers } = useTiers();
  const { update, remove } = useTierActions();
  // Each opening gets a fresh form, keyed on this count.
  const [editing, setEditing] = useState<{ tier: Tier | null; opening: number } | null>(null);
  const [deleting, setDeleting] = useState<Tier | null>(null);

  if (isLoadingTiers) return <p className="m-0">Loading tiers…</p>;
  if (tiersError) {
    return <AppErrorState error={tiersError} title="Could not load tiers" onRetry={() => void reloadTiers()} />;
  }

  const open = (tier: Tier | null) => setEditing((current) => ({ tier, opening: (current?.opening ?? 0) + 1 }));
  const toggleEnabled = (tier: Tier) =>
    update.mutate({ id: tier.id, data: { enabled: !tier.enabled } }, { onError: (error) => toastError(error) });

  return (
    <>
      <div className="mb-3 flex flex-wrap items-end justify-between gap-2">
        <p className="m-0 min-w-0 flex-1 basis-[24rem] text-[0.84rem]" style={{ color: "var(--ink-3)" }}>
          A change to a tier&apos;s agents, platforms or features reaches every organization on it straight away. A new
          price applies to new subscriptions only.
        </p>
        <button type="button" className="af-btn af-btn-sm" onClick={() => open(null)}>
          <Plus size={14} /> Add tier
        </button>
      </div>

      <div className="af-card overflow-x-auto p-0">
        <table className="w-full min-w-[46rem] border-collapse text-[0.84rem]" aria-label="Tiers">
          <thead>
            <tr style={{ color: "var(--ink-4)" }} className="text-left text-[0.75rem]">
              <th className="px-4 py-2.5 font-medium">Tier</th>
              <th className="px-4 py-2.5 font-medium">Price</th>
              <th className="px-4 py-2.5 font-medium">Usage</th>
              <th className="px-4 py-2.5 font-medium">Agents</th>
              <th className="px-4 py-2.5 font-medium">Offered</th>
              <th className="px-4 py-2.5" aria-label="Actions" />
            </tr>
          </thead>
          <tbody>
            {tiers.map((tier) => {
              const locked = tier.activation === "none";
              return (
                <tr key={tier.id} data-testid={`tier-row-${tier.key}`} style={{ borderTop: "1px solid var(--line)" }}>
                  <td className="px-4 py-3 align-top">
                    <span className="font-medium" style={{ color: "var(--ink)" }}>
                      {tier.name}
                    </span>
                    <span
                      className="ml-2 rounded-full px-2 py-0.5 text-[0.7rem] font-medium"
                      style={{ background: "var(--bg-soft)", color: "var(--ink-3)" }}
                    >
                      {ACTIVATION_LABELS[tier.activation]}
                    </span>
                    <span className="block text-[0.75rem]" style={{ color: "var(--ink-4)" }}>
                      {describePlatforms(tier.allowedPlatformKeys)} · {describeFeatures(tier.features)}
                    </span>
                  </td>
                  <td className="px-4 py-3 align-top" style={{ color: "var(--ink)" }}>
                    {describePrice(tier)}
                  </td>
                  <td className="px-4 py-3 align-top" style={{ color: "var(--ink)" }}>
                    {describeUsage(tier)}
                  </td>
                  <td className="px-4 py-3 align-top" style={{ color: "var(--ink)" }}>
                    {tier.agentLimit}
                  </td>
                  <td className="px-4 py-3 align-top">
                    <button
                      type="button"
                      role="switch"
                      aria-checked={tier.enabled}
                      aria-label={`${tier.name} offered`}
                      title={locked ? "The none tier is never offered" : undefined}
                      disabled={locked || update.isPending}
                      onClick={() => toggleEnabled(tier)}
                      className="relative h-5 w-9 shrink-0 rounded-full transition-colors disabled:cursor-not-allowed disabled:opacity-50"
                      style={{ backgroundColor: tier.enabled ? "var(--ink)" : "var(--line)" }}
                    >
                      <span
                        className={`absolute top-0.5 left-0.5 h-4 w-4 rounded-full bg-white transition-transform ${tier.enabled ? "translate-x-4" : ""}`}
                      />
                    </button>
                  </td>
                  <td className="px-4 py-3 text-right align-top">
                    {!locked && (
                      <DropdownMenu modal={false}>
                        <DropdownMenuTrigger asChild>
                          <button
                            type="button"
                            className="af-btn af-btn-ghost af-btn-icon"
                            aria-label={`${tier.name} actions`}
                          >
                            <MoreHorizontal size={16} />
                          </button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end">
                          <DropdownMenuItem onSelect={() => open(tier)}>Edit</DropdownMenuItem>
                          {!tier.isSystem && (
                            <DropdownMenuItem variant="destructive" onSelect={() => setDeleting(tier)}>
                              Delete
                            </DropdownMenuItem>
                          )}
                        </DropdownMenuContent>
                      </DropdownMenu>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {editing && (
        <TierDialog
          key={editing.opening}
          tier={editing.tier}
          open
          onOpenChange={(isOpen) => !isOpen && setEditing(null)}
        />
      )}

      <ConfirmationDialog
        open={deleting !== null}
        onOpenChange={(isOpen) => !isOpen && setDeleting(null)}
        variant="destructive"
        title={`Delete ${deleting?.name ?? "this tier"}?`}
        description="It is removed from the catalog. To stop offering it but keep it, turn it off instead."
        confirmLabel="Delete tier"
        pendingLabel="Deleting…"
        isPending={remove.isPending}
        onConfirm={() => {
          if (!deleting) return;
          remove.mutate(deleting.id, {
            onSuccess: () => setDeleting(null),
            onError: (error) => toastError(error),
          });
        }}
      />
    </>
  );
}
