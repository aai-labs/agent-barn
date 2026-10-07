import { formatUsd } from "@/features/organizations/spend-limit";

export type CascadeAgent = {
  name: string;
  /** The Agent's limit in force now. */
  limitUsd: number;
  ownLimitUsd?: number | null;
  spendUsd?: number | null;
};

export type Cascade = {
  lines: string[];
  /** The change stops model calls that work today, so it deserves a louder confirm. */
  stopsAgents: boolean;
};

const NAMED = 3;

function names(items: string[]) {
  if (items.length <= NAMED) return items.join(", ");
  return `${items.slice(0, NAMED).join(", ")} and ${items.length - NAMED} more`;
}

/**
 * What lowering the organization's limit to `next` will do, in the words the
 * confirmation shows: whether it cuts the organization or particular Agents off right
 * now, and which limits it pulls down with it. Built from what the server reported —
 * the organization's spend, its own default Agent limit, the default in force and each
 * Agent's limit and spend — so the preview and the change it describes can't disagree.
 */
export function describeCascade({
  next,
  organizationSpendUsd,
  ownDefault,
  effectiveDefault,
  agents,
  period,
  renews,
}: {
  next: number;
  organizationSpendUsd?: number | null;
  ownDefault: number | null;
  effectiveDefault: number;
  agents: CascadeAgent[];
  /** "this month" */
  period: string;
  /** "Oct 1, 2026", or null when the renewal date is not known yet. */
  renews: string | null;
}): Cascade {
  const until = renews ? ` until ${renews}` : " until the limit renews";
  const lines: string[] = [];
  let stopsAgents = false;

  if (organizationSpendUsd != null && organizationSpendUsd >= next) {
    stopsAgents = true;
    lines.push(
      `Your organization has already spent ${formatUsd(organizationSpendUsd)} ${period}, so no Agent can make model calls${until}.`,
    );
  } else {
    const stopped = agents
      .filter((agent) => agent.spendUsd != null && agent.spendUsd < agent.limitUsd && agent.spendUsd >= next)
      .map((agent) => agent.name);
    if (stopped.length > 0) {
      stopsAgents = true;
      lines.push(
        `${names(stopped)} ${stopped.length === 1 ? "has" : "have"} already spent more than that ${period} and will stop making model calls${until}.`,
      );
    }
  }

  if (ownDefault != null && ownDefault > next) {
    lines.push(`The default Agent limit will be lowered from ${formatUsd(ownDefault)} to ${formatUsd(next)}.`);
  } else if (ownDefault == null && effectiveDefault > next) {
    lines.push(`Agents following the default will be held to ${formatUsd(next)}.`);
  }

  const lowered = agents
    .filter((agent) => agent.ownLimitUsd != null && agent.ownLimitUsd > next)
    .map((agent) => `${agent.name} (${formatUsd(agent.ownLimitUsd as number)} → ${formatUsd(next)})`);
  if (lowered.length > 0) {
    lines.push(`Lowered to fit: ${names(lowered)}.`);
  }

  return { lines, stopsAgents };
}
