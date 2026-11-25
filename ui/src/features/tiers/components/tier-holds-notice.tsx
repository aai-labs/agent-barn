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
 * Said on the team page while something is on hold, so the owner finds where to choose what to
 * keep. Members see what is held; owners and admins get the link. A hold outlives the tier that
 * made it, so the notice only blames the current tier for what it really leaves out: when it
 * covers everything held, it says so and offers to turn it back on.
 */
export function TierHoldsNotice({ organizationId, heldAgents }: { organizationId: string; heldAgents: number }) {
  const { role } = useActiveOrgRole();
  const canChoose = role === "OWNER" || role === "ADMIN";
  const { holds } = useTierHolds(organizationId, canChoose);
  const { tier, hasFeature, allowsPlatform } = useTierEntitlements();

  const connections = holds?.connections ?? [];
  const webhooks = holds?.webhooks ?? [];
  const memory = holds?.memory ?? [];
  const parts = [
    heldAgents > 0 && count(heldAgents, "agent", "agents"),
    connections.length > 0 && count(connections.length, "channel", "channels"),
    webhooks.length > 0 && count(webhooks.length, "webhook", "webhooks"),
    memory.length > 0 && `memory on ${count(memory.length, "agent", "agents")}`,
  ].filter((part): part is string => Boolean(part));
  if (parts.length === 0) return null;

  const tierName = tier?.name ?? "Your tier";
  const leftOut =
    connections.some((connection) => !allowsPlatform(connection.platformKey ?? "")) ||
    (webhooks.length > 0 && !hasFeature("agent_webhooks")) ||
    (memory.length > 0 && !hasFeature("agent_memory"));
  // Only switched-off items the tier now includes: nothing to choose, just turn them back on.
  const releasable = heldAgents === 0 && !leftOut;
  const them = connections.length + webhooks.length + memory.length === 1 ? "it" : "them";

  return (
    <div
      role="status"
      className="mb-6 flex flex-wrap items-center justify-between gap-3 rounded-xl border px-4 py-3 text-sm"
      style={{ background: "var(--warn-soft)", borderColor: "var(--line)", color: "var(--ink)" }}
    >
      <span className="flex items-start gap-2">
        <PauseCircle size={16} aria-hidden className="mt-[2px] shrink-0" style={{ color: "var(--warn)" }} />
        {releasable ? (
          <span>
            On hold from an earlier tier: {joined(parts)}. {tierName} includes {them}, so you can turn {them} back on.
            Nothing has been deleted.
          </span>
        ) : (
          <span>
            {leftOut && `${tierName} doesn't cover everything your organization had. `}
            On hold: {joined(parts)}. Nothing has been deleted.
            {!canChoose && " An owner or admin can choose what to keep."}
          </span>
        )}
      </span>
      {canChoose && (
        <Link href={`/dashboard/${organizationId}/settings?tab=tier`} className="af-btn af-btn-sm">
          {releasable ? "Turn back on" : "Choose what to keep"}
        </Link>
      )}
    </div>
  );
}
