"use client";

import { useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation } from "@tanstack/react-query";
import { z } from "zod";
import { WandSparkles } from "lucide-react";

import { ConfirmationDialog } from "@/components/confirmation-dialog";

import { useCurrentUser } from "@/auth/providers/user-context-provider";
import { useCommunicationConnectionActions } from "@/features/communication-connections/hooks/use-communication-connections";
import { CommunicationConnectionSchema, type CommunicationConnection } from "@/features/communication-connections/schemas";
import { DoneStep } from "@/features/onboarding/components/done-step";
import { OnboardingDialogFrame } from "@/features/onboarding/components/onboarding-shell";
import { TelegramStep } from "@/features/onboarding/components/telegram-step";
import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";
import { useOrganizationContext } from "@/features/organizations/providers/organization-provider";
import { api } from "@/shared/api";
import { getErrorDisplay } from "@/shared/api/error/get-error-display";

import { useAgentNameSuggestion } from "../hooks/use-agent-name-suggestion";
import { useFetchAgent } from "../hooks/use-agent";
import { useCreateAgent } from "../hooks/use-create-agent";
import type { HiredAgent } from "../hooks/use-hire-agent-form";
import { useStartAgent } from "../hooks/use-start-agent";
import { formatAgentName } from "../naming";

/** The onboarding quick-start screens, scoped to a new Agent in the active Organization. */
export function QuickStartDialog({ onClose, onHired }: { onClose: () => void; onHired: (agent: HiredAgent) => void }) {
  const router = useRouter();
  const { user } = useCurrentUser();
  const { selectedOrganization } = useOrganizationContext();
  const orgApiBase = useOrganizationApiBase();
  const suggestion = useAgentNameSuggestion();
  const create = useCreateAgent();
  const start = useStartAgent();
  const fetchAgent = useFetchAgent();
  const { createConnection } = useCommunicationConnectionActions();
  const savedAgent = useRef<HiredAgent | null>(null);
  const [agent, setAgent] = useState<HiredAgent | null>(null);
  const [connection, setConnection] = useState<CommunicationConnection | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [running, setRunning] = useState(false);
  const [done, setDone] = useState(false);
  const [username, setUsername] = useState<string | null>(null);

  const setup = useMutation({
    mutationFn: async () => {
      let current = savedAgent.current;
      if (!current) {
        const firstName = suggestion.firstName ?? (await suggestion.retry()).data?.firstName;
        if (!firstName) throw new Error("We couldn't suggest an agent name. Try again.");
        const created = await create.mutateAsync({ name: formatAgentName(firstName, "General Purpose"), agentType: "hermes", templateKey: "general-purpose", approvalMode: "auto" });
        current = { id: created.id, name: created.name, role: "General Purpose" };
        savedAgent.current = current;
        setAgent(current);
      }
      // Read before creating on retries, including a Connection whose create
      // succeeded on the server but whose response was lost in transit.
      const existing = await api.get<CommunicationConnection[]>(`${orgApiBase}/agents/${current.id}/connections`, { schema: z.array(CommunicationConnectionSchema) });
      const telegram = existing.data.find((item) => item.platformKey === "agentbarn_telegram")
        ?? await createConnection.mutateAsync({ agentId: current.id, platformKey: "agentbarn_telegram", displayName: "Telegram", enabled: true, settings: {}, credentials: {} });
      setConnection(telegram);
      const latest = await fetchAgent(current.id);
      const started = latest.status === "RUNNING" ? latest : await start.mutateAsync(current.id);
      if (started.status !== "RUNNING") throw new Error("We couldn't start your agent. Try again.");
      setRunning(true);
    },
  });
  const home = `/dashboard/${selectedOrganization!.id}`;
  const botUsername = connection?.externalIdentity?.replace(/^@/, "") ?? null;
  function openChat() {
    if (!agent) return;
    onHired(agent);
    router.push(`${home}/agents/${agent.id}?tab=chat`);
  }

  if (!confirmed) {
    return (
      <ConfirmationDialog
        open
        onOpenChange={(open) => { if (!open) onClose(); }}
        title="Your ready-made assistant"
        description="A versatile teammate for everyday tasks: draft messages, research ideas, and plan your next steps."
        icon={<WandSparkles size={20} aria-hidden />}
        confirmLabel="Hire assistant"
        onConfirm={() => { setConfirmed(true); setup.mutate(); }}
      >
        <dl className="my-5 grid grid-cols-2 gap-x-4 gap-y-3 rounded-xl border p-4 text-sm" style={{ borderColor: "var(--line)", background: "var(--bg-soft)" }}>
          <dt style={{ color: "var(--ink-3)" }}>Template</dt><dd className="m-0 font-medium">General Purpose</dd>
          <dt style={{ color: "var(--ink-3)" }}>Runtime</dt><dd className="m-0 font-medium">Hermes</dd>
          <dt style={{ color: "var(--ink-3)" }}>Model</dt><dd className="m-0 font-medium">Organization default</dd>
        </dl>
        <p className="m-0 text-sm leading-relaxed" style={{ color: "var(--ink-3)" }}>
          We&apos;ll give your assistant a name and start it when you hire. Then connect Telegram, or skip straight to Web Chat. You can change its settings later.
        </p>
      </ConfirmationDialog>
    );
  }

  return (
    <OnboardingDialogFrame onClose={onClose} busy={setup.isPending}>
      {done && agent ? (
        <DoneStep email={user.email} creditUsd={null} path="quick" agentName={agent.name} telegramUsername={username} botUsername={botUsername} onDashboard={() => { onHired(agent); router.push(home); }} chatHref={`${home}/agents/${agent.id}?tab=chat`} channelsHref={`${home}/agents/${agent.id}/configuration?section=channels&connect=true`} />
      ) : (
        <TelegramStep email={user.email} creditUsd={null} botUsername={botUsername} agentName={agent?.name ?? "your assistant"} agent={running && agent && connection ? { id: agent.id, connectionId: connection.id } : null} hasAgent={!!agent} onLater={onClose} setUpError={setup.error ? getErrorDisplay(setup.error).description : null} onRetrySetUp={() => setup.mutate()} onContinue={(linked) => { setUsername(linked); setDone(true); }} isContinuing={false} onSkip={openChat} isSkipping={false} finishError={false} />
      )}
    </OnboardingDialogFrame>
  );
}
