"use client";

import Link from "next/link";
import { useState } from "react";
import { ArrowLeft, CircleAlert } from "lucide-react";

import { AppErrorState } from "@/components/app-error-state";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";

import { useAgent } from "../hooks/use-agent";
import { useAgentConfiguration } from "../hooks/use-agent-configuration";
import { useAgentHealth } from "../hooks/use-agent-health";
import { canAgent } from "../utils";
import { AgentAvatar } from "./agent-avatar";
import { AgentChannelSettings } from "./agent-channel-settings";
import { AgentConfigurationSidebar } from "./agent-configuration-sidebar";
import {
  AGENT_CONFIGURATION_SECTIONS,
  configurationSectionLabel,
  type AgentConfigurationSectionKey,
} from "./agent-configuration-utils";
import { AgentDangerZoneSettings } from "./agent-danger-zone-settings";
import { AgentKeysSettings } from "./agent-keys-settings";
import { AgentMetaBadges } from "./agent-meta-badges";
import { AgentOverrideSettings } from "./agent-override-settings";
import { AgentProfileSettings } from "./agent-profile-settings";
import { AgentSkillsSettings } from "./agent-skills-settings";
import { AgentTemplateSelectionSettings } from "./agent-template-selection-settings";

export function AgentConfigurationPage({ agentId }: { agentId: string }) {
  const {
    agent,
    isLoading: agentLoading,
    error: agentError,
    refetch: refetchAgent,
  } = useAgent(agentId);
  const {
    configuration,
    isLoading: configurationLoading,
    error: configurationError,
    refetch: refetchConfiguration,
  } = useAgentConfiguration(agentId);
  const canReadActivity = canAgent(agent, "activity.read");
  const { health } = useAgentHealth(
    agentId,
    canReadActivity && agent?.status === "ERROR",
  );
  const [activeSection, setActiveSection] = useState<AgentConfigurationSectionKey>("profile");
  const [editingSection, setEditingSection] = useState<AgentConfigurationSectionKey | null>(null);

  if (agentLoading || configurationLoading) {
    return (
      <div className="af-page animate-pulse">
        <div className="h-8 w-72 rounded-lg" style={{ background: "var(--bg-soft)" }} />
        <div className="mt-6 h-96 rounded-2xl" style={{ background: "var(--bg-soft)" }} />
      </div>
    );
  }

  if (agentError) {
    return (
      <div className="af-page">
        <AppErrorState
          error={agentError}
          title="We couldn't load this agent"
          onRetry={() => void refetchAgent()}
        />
      </div>
    );
  }

  if (configurationError) {
    return (
      <div className="af-page">
        <AppErrorState
          error={configurationError}
          title="We couldn't load this configuration"
          onRetry={() => void refetchConfiguration()}
        />
      </div>
    );
  }

  if (!agent || !configuration) return null;

  const homeHref = `/dashboard/${agent.organizationId}`;
  const canEdit = canAgent(agent, "agent.update");
  const canManageSecrets = canAgent(agent, "agent.secret.manage");
  const canDelete = canAgent(agent, "agent.delete");
  const section = AGENT_CONFIGURATION_SECTIONS.find((item) => item.key === activeSection) ?? AGENT_CONFIGURATION_SECTIONS[0];

  function selectSection(nextSection: AgentConfigurationSectionKey) {
    setActiveSection(nextSection);
    setEditingSection(null);
  }

  function toggleEditing(sectionKey: AgentConfigurationSectionKey) {
    setEditingSection((current) => (current === sectionKey ? null : sectionKey));
  }

  function handleOverridePublished() {
    setEditingSection(null);
    setActiveSection("template");
  }

  return (
    <div style={{ background: "var(--bg)" }}>
      <main className="af-page">
        <Link
          href={`${homeHref}/agents/${agent.id}`}
          className="mb-6 inline-flex items-center gap-1.5 rounded-lg px-2 py-1 text-[0.8125rem] transition-colors hover:bg-[var(--bg-soft)]"
          style={{ color: "var(--ink-3)" }}
        >
          <ArrowLeft size={14} /> Back to {agent.name}
        </Link>

        <div className="mb-8 flex flex-wrap items-start gap-4">
          <AgentAvatar agent={agent} size="lg" />
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-3">
              <h1 className="m-0 text-[2rem] font-semibold tracking-[-0.025em]" style={{ color: "var(--ink)" }}>
                Configuration
              </h1>
              <AgentMetaBadges agent={agent} variant="full" />
            </div>
            <p className="mb-0 mt-1 text-[0.9rem]" style={{ color: "var(--ink-3)" }}>
              {agent.name} · {agent.status === "STOPPED" ? "Stopped" : agent.status === "RUNNING" ? "Running · edits restart the Agent" : "Needs attention"}
            </p>
          </div>
          <div className="rounded-full border px-3 py-1.5 text-[0.78rem]" style={{ borderColor: "var(--line)", color: "var(--ink-3)" }}>
            {canEdit ? "Editor access" : "Read-only access"}
          </div>
        </div>

        {agent.status === "ERROR" && (
          <Alert
            variant="destructive"
            className="mb-8 items-start border-destructive/30 bg-destructive/5 px-4 py-3"
          >
            <CircleAlert aria-hidden />
            <AlertTitle>Agent needs attention</AlertTitle>
            <AlertDescription>
              <span className="block">
                The Agent could not start with its current configuration.
              </span>
              <span className="mt-1 block">
                {health?.reason
                  ? `Runtime reported: ${health.reason}`
                  : "Review the Agent logs, resolve the underlying issue, and start the Agent again."}
              </span>
              {canReadActivity && (
                <Link
                  href={`${homeHref}/agents/${agent.id}?tab=logs`}
                  className="mt-1 inline-block font-medium text-destructive underline underline-offset-3"
                >
                  View Agent logs
                </Link>
              )}
            </AlertDescription>
          </Alert>
        )}

        <div className="grid gap-8 lg:grid-cols-[14rem_minmax(0,1fr)] lg:items-start">
          <AgentConfigurationSidebar
            agent={agent}
            activeSection={activeSection}
            onSectionChange={selectSection}
          />

          <div className="min-w-0">
            <div className="mb-4">
              <h2 className="m-0 text-[1.25rem] font-semibold" style={{ color: "var(--ink)" }}>
                {configurationSectionLabel(activeSection, agent)}
              </h2>
              <p className="mb-0 mt-1 text-[0.84rem]" style={{ color: "var(--ink-3)" }}>
                {section.description}
              </p>
            </div>

            {activeSection === "template" && (
              <AgentTemplateSelectionSettings
                agent={agent}
                configuration={configuration}
                canEdit={canEdit}
              />
            )}
            {activeSection === "profile" && (
              <AgentProfileSettings
                agent={agent}
                canEdit={canEdit}
                editing={editingSection === "profile"}
                onEdit={() => toggleEditing("profile")}
              />
            )}
            {activeSection === "channels" && (
              <AgentChannelSettings
                agent={agent}
                canEdit={canEdit}
                editing={editingSection === "channels"}
                onEdit={() => toggleEditing("channels")}
              />
            )}
            {activeSection === "skills" && (
              <AgentSkillsSettings
                agent={agent}
                canEdit={canEdit}
                editing={editingSection === "skills"}
                onEdit={() => toggleEditing("skills")}
              />
            )}
            {activeSection === "keys" && (
              <AgentKeysSettings
                agent={agent}
                canEdit={canManageSecrets}
                editing={editingSection === "keys"}
                onEdit={() => toggleEditing("keys")}
              />
            )}
            {activeSection === "override" && (
              <AgentOverrideSettings
                agentId={agent.id}
                configuration={configuration}
                canEdit={canEdit}
                onPublished={handleOverridePublished}
              />
            )}
            {activeSection === "danger" && (
              <AgentDangerZoneSettings agent={agent} canDelete={canDelete} homeHref={homeHref} />
            )}
          </div>
        </div>
      </main>
    </div>
  );
}
