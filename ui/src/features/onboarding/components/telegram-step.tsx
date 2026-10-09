"use client";

import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Check, Copy, Loader2 } from "lucide-react";

import {
  telegramLinkTokenKey,
  useTelegramAccountLinkingActions,
  useTelegramLinkedAccounts,
  useTelegramLinkStatus,
} from "@/features/communication-connections/hooks/use-telegram-account-linking";
import { useOrganizationContext } from "@/features/organizations/providers/organization-provider";

import { StepAlert, StepHeading } from "./onboarding-shell";

// idle: a link is ready to open. waiting: opened, polling for Start.
type Phase = "idle" | "waiting";

/** Step 2: link the user's Telegram to their Agent through the shared bot. */
export function TelegramStep({
  agentId,
  connectionId,
  botUsername,
  onContinue,
  isContinuing,
}: {
  agentId: string;
  connectionId: string;
  botUsername: string | null;
  onContinue: (telegramUsername: string | null) => void;
  isContinuing: boolean;
}) {
  const queryClient = useQueryClient();
  const { selectedOrganization } = useOrganizationContext();
  const [phase, setPhase] = useState<Phase>("idle");
  // The link opened last ran out before anyone pressed Start; a fresh one is showing.
  const [expired, setExpired] = useState(false);
  const [copied, setCopied] = useState(false);
  const { createLink } = useTelegramAccountLinkingActions(agentId, connectionId);
  const pending = createLink.data?.url ? { id: createLink.data.id, url: createLink.data.url } : null;
  const { linkStatus } = useTelegramLinkStatus(agentId, connectionId, phase === "waiting" ? pending?.id ?? null : null);
  const { linkedAccounts, isLoadingLinkedAccounts } = useTelegramLinkedAccounts(agentId, connectionId, {
    whileLinking: phase === "waiting",
  });

  const linkedUsername = linkStatus?.status === "linked" ? linkStatus.telegramUsername : linkedAccounts[0]?.telegramUsername;
  const linked = linkStatus?.status === "linked" || linkedAccounts.length > 0;

  function newLink(onReady?: () => void) {
    createLink.mutate(undefined, { onSuccess: () => onReady?.() });
  }

  // A link is minted as soon as the step shows, so "Open in Telegram" is a plain link
  // the browser opens straight away rather than a pop-up it might block.
  const requested = useRef(false);
  useEffect(() => {
    if (requested.current || isLoadingLinkedAccounts || linkedAccounts.length > 0) return;
    requested.current = true;
    newLink();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- once, when the step first knows it isn't linked
  }, [isLoadingLinkedAccounts, linkedAccounts.length]);

  // The opened link ran out before anyone pressed Start: have a fresh one ready.
  const expiredTokenId = linkStatus?.status === "expired" ? pending?.id : undefined;
  useEffect(() => {
    if (!expiredTokenId) return;
    queryClient.removeQueries({
      queryKey: telegramLinkTokenKey.detail(`${selectedOrganization?.id ?? ""}:${connectionId}:${expiredTokenId}`),
    });
    newLink(() => {
      setPhase("idle");
      setExpired(true);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- once per expired link
  }, [expiredTokenId]);

  const bot = botUsername ? `@${botUsername}` : "our Telegram bot";

  return (
    <>
      <StepHeading title={`Say hi to ${bot}.`}>
        Open the bot and press <b>Start</b>. That links your Telegram to this account. Nothing to copy or type.
      </StepHeading>

      {linked ? (
        <div className="flex flex-col gap-4">
          <p className="m-0 flex items-center gap-2 text-[14px]" style={{ color: "var(--ok)" }}>
            <Check width={16} height={16} strokeWidth={2.5} aria-hidden />
            Linked as {linkedUsername ? `@${linkedUsername}` : "your Telegram account"}
          </p>
          <div>
            <button
              type="button"
              className="af-btn af-btn-primary af-btn-lg"
              disabled={isContinuing}
              onClick={() => onContinue(linkedUsername ?? null)}
            >
              {isContinuing && <Loader2 width={14} height={14} className="animate-spin" aria-hidden />}
              Continue
            </button>
          </div>
        </div>
      ) : createLink.isError ? (
        <div className="flex flex-col gap-4">
          <StepAlert>We couldn&apos;t create a Telegram link. Try again.</StepAlert>
          <div>
            <button type="button" className="af-btn af-btn-lg" onClick={() => newLink()}>
              Try again
            </button>
          </div>
        </div>
      ) : pending === null ? (
        <Waiting>Preparing your link…</Waiting>
      ) : phase === "waiting" ? (
        <div className="flex flex-col gap-3">
          <Waiting>Waiting for you to press Start in Telegram…</Waiting>
          <p className="m-0 text-[12.5px]" style={{ color: "var(--ink-3)" }}>
            Telegram didn&apos;t open?{" "}
            <a href={pending.url} target="_blank" rel="noreferrer" style={{ color: "var(--accent-ink)" }}>
              Open {botUsername ? `t.me/${botUsername}` : "the link"}
            </a>
          </p>
        </div>
      ) : (
        <div className="flex flex-col gap-4">
          {expired && <StepAlert>That link expired after 10 minutes. Here&apos;s a fresh one.</StepAlert>}
          <div className="flex flex-wrap items-center gap-3">
            <a
              href={pending.url}
              target="_blank"
              rel="noreferrer"
              className="af-btn af-btn-primary af-btn-lg"
              onClick={() => {
                setPhase("waiting");
                setExpired(false);
              }}
            >
              {expired ? "Open in Telegram again" : "Open in Telegram"}
            </a>
            <button
              type="button"
              className="af-btn af-btn-lg"
              onClick={() => {
                void navigator.clipboard.writeText(pending.url).then(() => {
                  setCopied(true);
                  setTimeout(() => setCopied(false), 1600);
                });
              }}
            >
              {copied ? <Check width={14} height={14} aria-hidden /> : <Copy width={14} height={14} aria-hidden />}
              {copied ? "Link copied" : "Copy link"}
            </button>
          </div>
        </div>
      )}
    </>
  );
}

function Waiting({ children }: { children: string }) {
  return (
    <p className="m-0 flex items-center gap-2 text-[13.5px]" role="status" style={{ color: "var(--ink-2)" }}>
      <Loader2 width={15} height={15} className="animate-spin" aria-hidden />
      {children}
    </p>
  );
}
