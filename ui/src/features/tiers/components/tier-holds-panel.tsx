"use client";

import { AppErrorState } from "@/components/app-error-state";
import { Badge } from "@/components/badge";
import { useOrganization } from "@/features/organizations/hooks/use-organization";
import { getErrorDisplay } from "@/shared/api/error/get-error-display";
import { toastError } from "@/shared/toast";

import { useTierEntitlements } from "../hooks/use-tier-entitlements";
import { useTierHoldActions, useTierHolds } from "../hooks/use-tier-holds";
import type { TierHeldItem } from "../schemas";
import { TIER_PLATFORMS } from "../utils";

const platformLabel = (key: string | null | undefined) =>
  TIER_PLATFORMS.find((platform) => platform.key === key)?.label ?? key ?? "";

/**
 * What the organization's tier covers and what it has put on hold. Owners and Admins choose
 * which agents to keep, and switch held items back on once the tier covers them.
 */
export function TierHoldsPanel({ organizationId, canManage }: { organizationId: string; canManage: boolean }) {
  const { organization } = useOrganization(organizationId);
  const { tier, hasFeature, allowsPlatform } = useTierEntitlements();
  const { holds, isLoading, error, refetch } = useTierHolds(organizationId, canManage);
  const { setAgentHold, reEnable } = useTierHoldActions(organizationId);

  if (!canManage) return null;
  if (error) {
    return <AppErrorState error={error} title="We couldn't load your tier" onRetry={() => void refetch()} retryLabel="Retry" />;
  }
  if (isLoading || !holds) return <p role="status">Loading…</p>;

  const limit = organization?.agentLimit ?? null;
  const kept = holds.agents.filter((agent) => !agent.suspendedAt).length;
  const hasRoom = limit === null || kept < limit;
  const agentsHeld = holds.agents.some((agent) => agent.suspendedAt);
  // Choosing which agents to keep only matters once the tier holds one, or is about to.
  const choosingAgents = agentsHeld || Boolean(organization?.overTier);
  const nothingHeld =
    !agentsHeld &&
    !holds.connections.length &&
    !holds.webhooks.length &&
    !holds.memory.length;

  return (
    <div className="flex flex-col gap-6">
      <section className="af-card p-5" aria-label="Your tier">
        <h2 className="m-0 text-[15px] font-semibold" style={{ color: "var(--ink)" }}>
          {tier ? tier.name : "No tier"}
        </h2>
        <p className="mb-0 mt-1 text-[13.5px]" style={{ color: "var(--ink-3)" }}>
          {limit === null ? "No agent limit." : `Up to ${limit} ${limit === 1 ? "agent" : "agents"} at a time.`}{" "}
          {nothingHeld
            ? "Everything your organization has is covered."
            : "What your tier doesn't cover is on hold. Nothing has been deleted."}
        </p>
        {organization?.overTier && organization.tierHoldsDueAt && (
          <p role="status" className="mb-0 mt-2 text-[13.5px]" style={{ color: "var(--warn)" }}>
            Your organization runs more than {tier?.name ?? "its tier"} covers. Choose what to keep by{" "}
            {new Date(organization.tierHoldsDueAt).toLocaleDateString()}; after that the oldest agents are kept.
          </p>
        )}
      </section>

      {choosingAgents && (
      <section aria-label="Agents">
        <h3 className="mb-2 mt-0 text-[0.95rem] font-semibold">Agents</h3>
        <p className="mb-3 mt-0 text-sm" style={{ color: "var(--ink-3)" }}>
          Agents on hold are stopped and can&apos;t start. To keep a different agent, put one on hold first to free its place.
        </p>
        <ul className="m-0 flex list-none flex-col gap-2 p-0">
          {holds.agents.map((agent) => (
            <li key={agent.id} className="flex items-center justify-between gap-3 rounded-xl border px-4 py-3" style={{ borderColor: "var(--line)" }}>
              <span className="flex items-center gap-2">
                <span className="font-medium">{agent.name}</span>
                {agent.suspendedAt ? <Badge variant="warn">On hold</Badge> : <Badge>Kept</Badge>}
              </span>
              {agent.suspendedAt ? (
                <button
                  type="button"
                  className="af-btn af-btn-sm"
                  disabled={!hasRoom || setAgentHold.isPending}
                  title={hasRoom ? undefined : "Put another agent on hold first."}
                  onClick={() => void setAgentHold.mutateAsync({ agentId: agent.id, hold: false }).catch(toastError)}
                >
                  Release {agent.name}
                </button>
              ) : (
                <button
                  type="button"
                  className="af-btn af-btn-sm"
                  disabled={setAgentHold.isPending}
                  onClick={() => void setAgentHold.mutateAsync({ agentId: agent.id, hold: true }).catch(toastError)}
                >
                  Put {agent.name} on hold
                </button>
              )}
            </li>
          ))}
        </ul>
      </section>
      )}

      <HeldList
        title="Channels"
        items={holds.connections}
        describe={(item) => `${item.name} · ${platformLabel(item.platformKey)} · ${item.agentName}`}
        allowed={(item) => allowsPlatform(item.platformKey ?? "")}
        isPending={reEnable.isPending}
        onReEnable={(item) => void reEnable.mutateAsync({ kind: "connection", item }).catch(toastError)}
      />
      <HeldList
        title="Webhooks"
        items={holds.webhooks}
        describe={(item) => `${item.name} · ${item.agentName}`}
        allowed={() => hasFeature("agent_webhooks")}
        isPending={reEnable.isPending}
        onReEnable={(item) => void reEnable.mutateAsync({ kind: "webhook", item }).catch(toastError)}
      />
      <HeldList
        title="Long-term memory"
        items={holds.memory}
        describe={(item) => item.agentName}
        allowed={() => hasFeature("agent_memory")}
        isPending={reEnable.isPending}
        onReEnable={(item) => void reEnable.mutateAsync({ kind: "memory", item }).catch(toastError)}
      />
      {setAgentHold.isError && (
        <p role="alert" className="m-0 text-sm" style={{ color: "var(--err)" }}>
          {getErrorDisplay(setAgentHold.error).description}
        </p>
      )}
    </div>
  );
}

function HeldList({
  title,
  items,
  describe,
  allowed,
  isPending,
  onReEnable,
}: {
  title: string;
  items: TierHeldItem[];
  describe: (item: TierHeldItem) => string;
  allowed: (item: TierHeldItem) => boolean;
  isPending: boolean;
  onReEnable: (item: TierHeldItem) => void;
}) {
  if (!items.length) return null;
  return (
    <section aria-label={`${title} on hold`}>
      <h3 className="mb-2 mt-0 text-[0.95rem] font-semibold">{title} on hold</h3>
      <ul className="m-0 flex list-none flex-col gap-2 p-0">
        {items.map((item) => (
          <li key={item.id} className="flex items-center justify-between gap-3 rounded-xl border px-4 py-3" style={{ borderColor: "var(--line)" }}>
            <span>{describe(item)}</span>
            <button
              type="button"
              className="af-btn af-btn-sm"
              disabled={!allowed(item) || isPending}
              title={allowed(item) ? undefined : "Your organization's tier doesn't include this."}
              onClick={() => onReEnable(item)}
            >
              Re-enable
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
