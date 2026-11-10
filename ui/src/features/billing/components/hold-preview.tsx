"use client";

import { TIER_PLATFORMS } from "@/features/tiers/utils";

import { useHoldPreview } from "../hooks/use-hold-preview";

const platformLabel = (key: string | null | undefined) =>
  TIER_PLATFORMS.find((platform) => platform.key === key)?.label ?? key ?? "";

const count = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

/**
 * What a downgrade would put on hold, shown before the owner confirms it. Nothing is deleted,
 * and the owner chooses which agents to keep afterwards in Settings, Tier.
 */
export function HoldPreview({ organizationId, tierKey }: { organizationId: string; tierKey: string | null }) {
  const { preview, isLoading, error } = useHoldPreview(organizationId, tierKey);

  if (!tierKey) return null;
  if (isLoading) {
    return (
      <p role="status" className="mb-0 mt-2 text-[13px]" style={{ color: "var(--ink-3)" }}>
        Checking what {tierKey === "free" ? "Free" : "that tier"} covers…
      </p>
    );
  }
  if (error || !preview) {
    return (
      <p className="mb-0 mt-2 text-[13px]" style={{ color: "var(--ink-3)" }}>
        We couldn&apos;t check what the new tier covers. Anything it leaves out goes on hold; nothing is deleted.
      </p>
    );
  }

  const lines = [
    preview.agents.length > 0 &&
      `${count(preview.agents.length, "agent", "agents")}: ${preview.agents.map((agent) => agent.name).join(", ")}`,
    preview.connections.length > 0 &&
      `${count(preview.connections.length, "channel", "channels")}: ${preview.connections
        .map((item) => `${item.name} (${platformLabel(item.platformKey)})`)
        .join(", ")}`,
    preview.webhooks.length > 0 &&
      `${count(preview.webhooks.length, "webhook", "webhooks")}: ${preview.webhooks.map((item) => item.name).join(", ")}`,
    preview.memory.length > 0 && `Long-term memory on ${preview.memory.map((item) => item.agentName).join(", ")}`,
  ].filter((line): line is string => Boolean(line));

  if (lines.length === 0) {
    return (
      <p className="mb-0 mt-2 text-[13px]" style={{ color: "var(--ink-3)" }}>
        {`${preview.tier} covers everything your organization runs now.`}
      </p>
    );
  }
  return (
    <div className="mt-2 flex flex-col gap-2 text-[13px]" aria-label="What goes on hold">
      <p className="m-0" style={{ color: "var(--ink-2)" }}>
        {`${preview.tier} doesn't cover everything your organization runs now. These go on hold, and nothing is deleted:`}
      </p>
      <ul className="m-0 flex list-disc flex-col gap-1 pl-5" style={{ color: "var(--ink)" }}>
        {lines.map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ul>
      {preview.agents.length > 0 && (
        <p className="m-0" style={{ color: "var(--ink-3)" }}>
          The oldest agents are kept. You can choose different ones afterwards in Settings, Tier.
        </p>
      )}
    </div>
  );
}
