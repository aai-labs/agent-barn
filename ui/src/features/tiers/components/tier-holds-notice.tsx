"use client";

import Link from "next/link";
import { PauseCircle } from "lucide-react";

import { useActiveOrgRole } from "@/features/organizations/hooks/use-active-org-role";

import { useTierEntitlements } from "../hooks/use-tier-entitlements";
import { useTierHolds } from "../hooks/use-tier-holds";

const count = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

function joined(parts: string[]) {
  return parts.length <= 1 ? (parts[0] ?? "") : `${parts.slice(0, -1).join(", ")} and ${parts[parts.length - 1]}`;
}

/**
 * Said on the team page while the organization's tier has put something on hold, so the owner
 * finds where to choose what to keep. Members see what is held; owners and admins get the link.
 */
export function TierHoldsNotice({ organizationId, heldAgents }: { organizationId: string; heldAgents: number }) {
  const { role } = useActiveOrgRole();
  const canChoose = role === "OWNER" || role === "ADMIN";
  const { holds } = useTierHolds(organizationId, canChoose);
  const { tier } = useTierEntitlements();

  const parts = [
    heldAgents > 0 && count(heldAgents, "agent", "agents"),
    holds && holds.connections.length > 0 && count(holds.connections.length, "channel", "channels"),
    holds && holds.webhooks.length > 0 && count(holds.webhooks.length, "webhook", "webhooks"),
    holds && holds.memory.length > 0 && `memory on ${count(holds.memory.length, "agent", "agents")}`,
  ].filter((part): part is string => Boolean(part));
  if (parts.length === 0) return null;

  return (
    <div
      role="status"
      className="mb-6 flex flex-wrap items-center justify-between gap-3 rounded-xl border px-4 py-3 text-sm"
      style={{ background: "var(--warn-soft)", borderColor: "var(--line)", color: "var(--ink)" }}
    >
      <span className="flex items-start gap-2">
        <PauseCircle size={16} aria-hidden className="mt-[2px] shrink-0" style={{ color: "var(--warn)" }} />
        <span>
          {tier ? `${tier.name} doesn't cover everything your organization had.` : "Your tier doesn't cover everything."}{" "}
          On hold: {joined(parts)}. Nothing has been deleted.
          {!canChoose && " An owner or admin can choose what to keep."}
        </span>
      </span>
      {canChoose && (
        <Link href={`/dashboard/${organizationId}/settings?tab=tier`} className="af-btn af-btn-sm">
          Choose what to keep
        </Link>
      )}
    </div>
  );
}
