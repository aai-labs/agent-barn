"use client";

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { MessageCircle } from "lucide-react";

import { useCurrentUser } from "@/auth/providers/user-context-provider";
import { telegramLinkedAccountsKey, useTelegramLinkedAccounts } from "@/features/communication-connections/hooks/use-telegram-account-linking";
import type { CommunicationConnection } from "@/features/communication-connections/schemas";
import { OnboardingDialogFrame } from "@/features/onboarding/components/onboarding-shell";
import { TelegramStep } from "@/features/onboarding/components/telegram-step";

import type { Agent } from "../schemas";

/** Resume linking an existing shared-bot Connection; never provision another Agent. */
export function AgentTelegramSetup({ agent, connection, onOpenChat }: { agent: Agent; connection: CommunicationConnection; onOpenChat: () => void }) {
  const { user } = useCurrentUser();
  const queryClient = useQueryClient();
  const { linkedAccounts, isLoadingLinkedAccounts } = useTelegramLinkedAccounts(agent.id, connection.id);
  const [open, setOpen] = useState(false);
  const running = agent.status === "RUNNING";

  function close() {
    setOpen(false);
    void queryClient.invalidateQueries({ queryKey: telegramLinkedAccountsKey.list({ organizationId: agent.organizationId, agentId: agent.id, connectionId: connection.id }) });
  }

  return (
    <>
      {!isLoadingLinkedAccounts && linkedAccounts.length === 0 && (
        <div className="mb-6 flex flex-col gap-4 rounded-xl border p-5 sm:flex-row sm:items-center sm:justify-between" style={{ borderColor: "var(--line)", background: "var(--bg-elev)" }}>
          <div className="flex items-start gap-3">
            <MessageCircle size={20} className="mt-0.5 shrink-0" aria-hidden style={{ color: "var(--accent-ink)" }} />
            <div>
              <p className="m-0 font-semibold">Finish connecting Telegram</p>
              <p className="mb-0 mt-1 text-sm leading-relaxed" style={{ color: "var(--ink-3)" }}>
                {running ? "Link your Telegram account to chat with your assistant there. You can continue using Web Chat anytime." : "Start your agent, then link your Telegram account to chat with it there."}
              </p>
            </div>
          </div>
          <button type="button" className="af-btn af-btn-primary shrink-0 self-start sm:self-auto" disabled={!running} onClick={() => setOpen(true)}>Connect Telegram</button>
        </div>
      )}
      {open && (
        <OnboardingDialogFrame onClose={close} busy={false}>
          <TelegramStep
            email={user.email}
            creditUsd={null}
            botUsername={connection.externalIdentity?.replace(/^@/, "") ?? null}
            agentName={agent.name}
            agent={{ id: agent.id, connectionId: connection.id }}
            setUpError={null}
            onRetrySetUp={() => {}}
            onContinue={close}
            isContinuing={false}
            onSkip={() => { close(); onOpenChat(); }}
            isSkipping={false}
            finishError={false}
          />
        </OnboardingDialogFrame>
      )}
    </>
  );
}
