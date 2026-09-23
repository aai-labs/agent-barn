"use client";

import type { ReactNode } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { format, formatDistanceToNow } from "date-fns";
import { KeyRound, Plug, Sparkles } from "lucide-react";

import { Badge } from "@/components/badge";
import { platformIcon } from "@/components/brand-icons";
import { Skeleton } from "@/components/ui/skeleton";
import {
  useCommunicationConnections,
  useCommunicationPlatforms,
} from "@/features/communication-connections/hooks/use-communication-connections";
import type { CommunicationConnection } from "@/features/communication-connections/schemas";
import { SkillScopeBadge } from "@/features/skills/components/skill-scope-badge";
import { SkillSourceBadge } from "@/features/skills/components/skill-source-badge";
import { skillDetailHref } from "@/features/skills/scope";
import { SKILL_PROVIDER_LABELS } from "@/features/skills/utils";

import { useAgentTemplate } from "../hooks/use-agent-template";
import type { Agent, AgentAssignedSkill, AgentSecretRead, CommandApprovalMode } from "../schemas";
import { canAgent, currentModelOf, formatModelName } from "../utils";
import { ModelSourceBadge } from "./model-source-badge";

const RUNTIME_LABELS = { hermes: "Hermes", openclaw: "OpenClaw" } as const;

const APPROVAL_LABELS: Record<CommandApprovalMode, string> = {
  auto: "Auto — low-risk commands run without asking",
  manual: "Manual — every command waits for approval",
  off: "Off — commands run without an approval prompt",
};

function providerLabel(provider: string): string {
  return SKILL_PROVIDER_LABELS[provider] ?? provider;
}

function formatDay(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "—" : format(date, "MMM d, yyyy");
}

function formatAgo(value: string): string | null {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : formatDistanceToNow(date, { addSuffix: true });
}

/** Everything on this tab that describes the Agent itself, above its spend. */
export function AgentAboutProfile({ agent }: { agent: Agent }) {
  const params = useParams();
  const orgId = typeof params?.orgId === "string" ? params.orgId : null;
  const configurationHref = (section: string) =>
    orgId ? `/dashboard/${orgId}/agents/${agent.id}/configuration?section=${section}` : "#";

  return (
    <div className="flex flex-col gap-4">
      <OverviewSection agent={agent} configurationHref={configurationHref} />
      <SkillsSection agent={agent} orgId={orgId} configurationHref={configurationHref} />
      <div className="grid gap-4 lg:grid-cols-2">
        <MessagingSection agent={agent} configurationHref={configurationHref} />
        <IntegrationsSection agent={agent} configurationHref={configurationHref} />
      </div>
    </div>
  );
}

type SectionHrefs = (section: string) => string;

function OverviewSection({
  agent,
  configurationHref,
}: {
  agent: Agent;
  configurationHref: SectionHrefs;
}) {
  // One pinned version, not the configuration history: the Agent already
  // carries the pinned version number, so only the display name and
  // description need a read, and this one does not grow with every published
  // version the way /configuration does.
  const { template } = useAgentTemplate(agent.id, agent.templateVersion);
  const isHermes = agent.agentType === "hermes";
  const hiredAgo = formatAgo(agent.createdAt);

  return (
    <Section
      title="Overview"
      description={`How ${agent.name} is set up right now.`}
      action={
        <Link href={configurationHref("profile")} className="af-btn af-btn-sm">
          Configuration
        </Link>
      }
      testId="agent-about-overview"
    >
      {template?.description && (
        <p className="m-0 mb-4 max-w-[70ch] text-[13px] leading-relaxed" style={{ color: "var(--ink-2)" }}>
          {template.description}
        </p>
      )}

      <dl className="m-0 grid gap-x-8 gap-y-4 sm:grid-cols-2 lg:grid-cols-3">
        <Fact label="Runtime">{RUNTIME_LABELS[agent.agentType]}</Fact>
        <Fact label="Model">
          <span className="font-mono text-[0.84rem]">
            {formatModelName(currentModelOf(agent)) || "—"}
          </span>
          <ModelSourceBadge source={agent.modelSource} />
        </Fact>
        <Fact label="Blueprint">
          <span className="truncate">{template?.templateName || agent.templateKey}</span>
          <span className="text-[0.78rem] tabular-nums" style={{ color: "var(--ink-4)" }}>
            v{agent.templateVersion}
          </span>
          {agent.templatePinType === "override" && <Badge variant="accent">Customised</Badge>}
        </Fact>
        <Fact label="Command approval">
          {isHermes ? APPROVAL_LABELS[agent.approvalMode] : "Full access — no approval prompts"}
        </Fact>
        {isHermes && (
          <Fact label="Verbose mode">
            {agent.verboseMode ? "Shows progress while working" : "Only the final reply is sent"}
          </Fact>
        )}
        <Fact label="Hired">
          {formatDay(agent.createdAt)}
          {hiredAgo && (
            <span className="text-[0.78rem]" style={{ color: "var(--ink-4)" }}>
              {hiredAgo}
            </span>
          )}
        </Fact>
      </dl>
    </Section>
  );
}

function SkillsSection({
  agent,
  orgId,
  configurationHref,
}: {
  agent: Agent;
  orgId: string | null;
  configurationHref: SectionHrefs;
}) {
  return (
    <Section
      title={`Skills (${agent.skills.length})`}
      description={`Configured skills for ${agent.name}`}
      action={
        <Link href={configurationHref("skills")} className="af-btn af-btn-sm">
          {canAgent(agent, "agent.update") ? "Manage skills" : "View skills"}
        </Link>
      }
      testId="agent-about-skills"
    >
      {agent.skills.length === 0 ? (
        <EmptyHint>
          No skills assigned yet — {agent.name} can only do what its blueprint describes.
        </EmptyHint>
      ) : (
        <ul className="m-0 grid list-none gap-2 p-0 sm:grid-cols-2 xl:grid-cols-3">
          {agent.skills.map((skill) => (
            <SkillTile key={skill.id} agentId={agent.id} orgId={orgId} skill={skill} />
          ))}
        </ul>
      )}
    </Section>
  );
}

function SkillTile({
  agentId,
  orgId,
  skill,
}: {
  agentId: string;
  orgId: string | null;
  skill: AgentAssignedSkill;
}) {
  const href = orgId ? skillDetailHref({ kind: "agent", agentId }, orgId, skill.id) : "#";

  return (
    <li>
      <Link href={href} className="block h-full no-underline">
        <Tile className="flex h-full flex-col gap-2">
          <div className="flex items-start justify-between gap-2">
            <span className="flex min-w-0 items-center gap-2">
              <Sparkles size={14} style={{ color: "var(--ink-4)", flexShrink: 0 }} />
              <span className="truncate text-[13.5px] font-semibold" style={{ color: "var(--ink)" }}>
                {skill.name}
              </span>
            </span>
            <span className="shrink-0 text-[11px] tabular-nums" style={{ color: "var(--ink-4)" }}>
              v{skill.version}
            </span>
          </div>

          <div className="flex flex-wrap items-center gap-1.5">
            {skill.required && <Badge variant="accent">Required</Badge>}
            {skill.updateAvailable && <Badge variant="warn">Update available</Badge>}
            {skill.scope && <SkillScopeBadge scope={skill.scope} />}
            <SkillSourceBadge source={skill.source} />
          </div>

          {skill.requiredProviders.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {skill.requiredProviders.map((provider) => (
                <Chip key={provider}>{providerLabel(provider)}</Chip>
              ))}
            </div>
          )}
        </Tile>
      </Link>
    </li>
  );
}

function MessagingSection({
  agent,
  configurationHref,
}: {
  agent: Agent;
  configurationHref: SectionHrefs;
}) {
  const connections = useCommunicationConnections(agent.id);
  const platforms = useCommunicationPlatforms();
  // The server's names, not the key: `teams` is "Microsoft Teams" and `web` is
  // "Web Chat". The capitalised key only stands in until the list arrives.
  const platformName = (platformKey: string) =>
    platforms.data?.find((platform) => platform.key === platformKey)?.displayName ??
    platformLabel(platformKey);

  return (
    <Section
      title="Messaging"
      description={`Where your team can reach ${agent.name}.`}
      action={
        <Link href={configurationHref("channels")} className="af-btn af-btn-sm">
          {canAgent(agent, "agent.update") ? "Manage" : "View"}
        </Link>
      }
      testId="agent-about-messaging"
    >
      {connections.data ? (
        connections.data.length === 0 ? (
          <EmptyHint>No connections yet — {agent.name} is reachable in Web Chat only.</EmptyHint>
        ) : (
          <ul className="m-0 flex list-none flex-col gap-2 p-0">
            {connections.data.map((connection) => (
              <ConnectionTile
                key={connection.id}
                connection={connection}
                platformName={platformName(connection.platformKey)}
              />
            ))}
          </ul>
        )
      ) : connections.isPending ? (
        <Skeleton className="h-[72px] w-full" />
      ) : agent.configuredPlatformKeys.length > 0 ? (
        // The connection list is a separate read; the Agent itself still knows
        // which platforms it is configured for.
        <div className="flex flex-wrap gap-1.5">
          {agent.configuredPlatformKeys.map((platformKey) => (
            <Chip key={platformKey}>{platformName(platformKey)}</Chip>
          ))}
        </div>
      ) : (
        <EmptyHint>We couldn&apos;t load this agent&apos;s connections.</EmptyHint>
      )}
    </Section>
  );
}

function ConnectionTile({
  connection,
  platformName,
}: {
  connection: CommunicationConnection;
  platformName: string;
}) {
  const status = connectionStatus(connection);

  return (
    <li>
      <Tile className="flex items-center gap-3">
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg" style={{ background: "var(--bg-elev)", border: "1px solid var(--line)", color: "var(--ink-3)" }}>
          {platformIcon(connection.platformKey, { size: 15 }) ?? <Plug size={15} />}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[13px] font-medium" style={{ color: "var(--ink)" }}>
            {connection.displayName}
          </span>
          <span className="block truncate text-[11.5px]" style={{ color: "var(--ink-4)" }}>
            {connection.externalIdentity
              ? `Connected as ${connection.externalIdentity}`
              : platformName}
          </span>
        </span>
        <span className="flex shrink-0 items-center gap-1.5 text-[11.5px]" style={{ color: status.color }}>
          <span aria-hidden className="h-1.5 w-1.5 rounded-full" style={{ background: status.color }} />
          {status.label}
        </span>
      </Tile>
    </li>
  );
}

function IntegrationsSection({
  agent,
  configurationHref,
}: {
  agent: Agent;
  configurationHref: SectionHrefs;
}) {
  const secrets = agent.secrets ?? [];

  return (
    <Section
      title="Integrations"
      description={`The accounts ${agent.name} can act through.`}
      action={
        // Keys are governed separately from the rest of the configuration.
        <Link href={configurationHref("keys")} className="af-btn af-btn-sm">
          {canAgent(agent, "agent.secret.manage") ? "Manage" : "View"}
        </Link>
      }
      testId="agent-about-integrations"
    >
      {secrets.length === 0 ? (
        <EmptyHint>No integration credentials stored for this agent.</EmptyHint>
      ) : (
        <ul className="m-0 flex list-none flex-col gap-2 p-0">
          {secrets.map((secret) => (
            <IntegrationTile key={secret.secretName} secret={secret} />
          ))}
        </ul>
      )}
    </Section>
  );
}

function IntegrationTile({ secret }: { secret: AgentSecretRead }) {
  return (
    <li>
      <Tile className="flex items-center gap-3">
        <KeyRound size={15} style={{ color: "var(--ink-4)", flexShrink: 0 }} />
        <span className="min-w-0 flex-1 truncate text-[13px] font-medium" style={{ color: "var(--ink)" }}>
          {providerLabel(secret.provider)}
        </span>
        {secret.sharedCredentialId ? (
          <Badge title={secret.sharedCredentialName ?? undefined}>
            Shared{secret.sharedCredentialName ? ` · ${secret.sharedCredentialName}` : ""}
          </Badge>
        ) : (
          <Badge>Agent-owned</Badge>
        )}
      </Tile>
    </li>
  );
}

function Section({
  title,
  description,
  action,
  testId,
  children,
}: {
  title: string;
  description: string;
  action?: ReactNode;
  testId: string;
  children: ReactNode;
}) {
  return (
    <section className="af-card p-4" data-testid={testId} aria-label={title}>
      <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="m-0 text-[14px] font-semibold" style={{ color: "var(--ink)" }}>
            {title}
          </h2>
          <p className="m-0 mt-1 text-[12px]" style={{ color: "var(--ink-4)" }}>
            {description}
          </p>
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-[0.72rem] font-semibold uppercase tracking-[0.08em]" style={{ color: "var(--ink-4)" }}>
        {label}
      </dt>
      <dd className="mb-0 mt-1 flex flex-wrap items-center gap-2 text-[0.9rem]" style={{ color: "var(--ink-2)" }}>
        {children}
      </dd>
    </div>
  );
}

function Tile({ className = "", children }: { className?: string; children: ReactNode }) {
  return (
    <div
      className={`rounded-xl px-3.5 py-3 ${className}`}
      style={{ border: "1px solid var(--line)", background: "var(--bg-soft)" }}
    >
      {children}
    </div>
  );
}

function Chip({ children }: { children: ReactNode }) {
  return (
    <span
      className="inline-flex items-center rounded-md px-2 py-0.5 text-[11px] font-medium"
      style={{ background: "var(--bg-elev)", color: "var(--ink-3)", border: "1px solid var(--line)" }}
    >
      {children}
    </span>
  );
}

function EmptyHint({ children }: { children: ReactNode }) {
  return (
    <p className="m-0 text-[12.5px]" style={{ color: "var(--ink-4)" }}>
      {children}
    </p>
  );
}

function platformLabel(platformKey: string): string {
  return platformKey.charAt(0).toUpperCase() + platformKey.slice(1);
}

function connectionStatus(connection: CommunicationConnection): { color: string; label: string } {
  if (!connection.enabled) return { color: "var(--ink-4)", label: "Disabled" };
  switch (connection.observedStatus) {
    case "CONNECTED":
      return { color: "var(--ok)", label: "Connected" };
    case "DEGRADED":
      return { color: "var(--warn)", label: "Degraded" };
    case "ERROR":
      return { color: "var(--err)", label: "Error" };
    case "CONNECTING":
      return { color: "var(--warn)", label: "Connecting…" };
    case "PENDING":
    default:
      return { color: "var(--ink-4)", label: "Waiting" };
  }
}
