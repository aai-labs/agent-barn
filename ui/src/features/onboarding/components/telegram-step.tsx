"use client";

import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Check, Copy } from "lucide-react";
import { QRCodeSVG } from "qrcode.react";

import {
  telegramLinkTokenKey,
  useTelegramAccountLinkingActions,
  useTelegramLinkedAccounts,
  useTelegramLinkStatus,
} from "@/features/communication-connections/hooks/use-telegram-account-linking";
import { useOrganizationContext } from "@/features/organizations/providers/organization-provider";

import { OnboardingShell, StepAlert, StepStatus } from "./onboarding-shell";

type ShellProps = { email: string; creditUsd: number | null };

type TelegramStepProps = ShellProps & {
  botUsername: string | null;
  agentName: string;
  /** Set once the Agent runs with its Telegram Connection; until then setup is shown. */
  agent: { id: string; connectionId: string } | null;
  /** Why setting the Agent up failed, if it did. */
  setUpError: string | null;
  onRetrySetUp: () => void;
  onContinue: (telegramUsername: string | null) => void;
  isContinuing: boolean;
  onSkip: () => void;
  isSkipping: boolean;
  /** Finishing onboarding (continue or skip) failed. */
  finishError: boolean;
};

/** Step 3 of quick start: link the user's Telegram to their Agent through the shared bot. */
export function TelegramStep(props: TelegramStepProps) {
  return props.agent ? <TelegramLinking {...props} agent={props.agent} /> : <AgentSetUp {...props} />;
}

function TelegramShell({
  email,
  creditUsd,
  botUsername,
  footerStart,
  footerEnd,
  status,
  link,
}: ShellProps & {
  botUsername: string | null;
  footerStart?: React.ReactNode;
  footerEnd: React.ReactNode;
  status: React.ReactNode;
  link: string | null;
}) {
  const bot = botUsername ? `@${botUsername}` : "our Telegram bot";
  return (
    <OnboardingShell
      step={2}
      path="quick"
      email={email}
      creditUsd={creditUsd}
      title={`Say hi to ${bot}`}
      subtitle="Your agent lives in Telegram. Linking takes one tap. Nothing to copy or type."
      footerStart={footerStart}
      footerEnd={footerEnd}
    >
      <div className="grid items-start gap-9 md:grid-cols-[1fr_auto]">
        <div className="flex flex-col gap-5">
          <ol className="m-0 flex list-none flex-col gap-3 p-0 text-[14px]" style={{ color: "var(--ink-2)" }}>
            {[`Open ${bot} in Telegram.`, "Press Start.", "Come back here. This page notices by itself."].map(
              (text, index) => (
                <li key={text} className="flex items-center gap-3">
                  <span
                    aria-hidden
                    className="grid size-[22px] shrink-0 place-items-center rounded-full border text-[11.5px] font-semibold"
                    style={{ background: "var(--bg-soft)", borderColor: "var(--line)", color: "var(--ink-3)" }}
                  >
                    {index + 1}
                  </span>
                  {text}
                </li>
              ),
            )}
          </ol>
          {status}
        </div>
        <div
          className="hidden rounded-[14px] border p-3.5 text-center transition-opacity md:block"
          style={{ borderColor: "var(--line)", opacity: link ? 1 : 0.35 }}
        >
          {link ? (
            <QRCodeSVG value={link} size={124} fgColor="#1a1815" aria-label="QR code that opens the bot" />
          ) : (
            <div className="size-[124px] rounded-md" style={{ background: "var(--bg-soft)" }} />
          )}
          <p className="mb-0 mt-2 text-[11.5px]" style={{ color: "var(--ink-3)" }}>
            On your phone?
            <br />
            Scan to open the bot.
          </p>
        </div>
      </div>
    </OnboardingShell>
  );
}

function StateBox({ ok = false, children }: { ok?: boolean; children: React.ReactNode }) {
  return (
    <div
      className="flex flex-col gap-1.5 rounded-xl border px-4 py-3.5"
      style={{ background: ok ? "var(--ok-soft)" : "var(--bg-soft)", borderColor: ok ? "transparent" : "var(--line)" }}
    >
      {children}
    </div>
  );
}

function Hint({ children, ok = false }: { children: React.ReactNode; ok?: boolean }) {
  return (
    <span className="text-[12.5px]" style={{ color: ok ? "var(--ok)" : "var(--ink-3)" }}>
      {children}
    </span>
  );
}

function SkipLink({ onSkip, isSkipping }: { onSkip: () => void; isSkipping: boolean }) {
  return (
    <button
      type="button"
      className="text-[12.5px] disabled:opacity-50"
      style={{ color: "var(--accent-ink)" }}
      disabled={isSkipping}
      onClick={onSkip}
    >
      {isSkipping ? "Opening the dashboard…" : "Skip, I'll chat on the web"}
    </button>
  );
}

/** Before the Agent runs: creating and starting it, or why that failed. */
function AgentSetUp({ email, creditUsd, botUsername, agentName, setUpError, onRetrySetUp }: TelegramStepProps) {
  return (
    <TelegramShell
      email={email}
      creditUsd={creditUsd}
      botUsername={botUsername}
      link={null}
      status={
        setUpError ? (
          <StepAlert>{setUpError}</StepAlert>
        ) : (
          <StateBox>
            <StepStatus>Starting {agentName}…</StepStatus>
            <Hint>This takes a few seconds.</Hint>
          </StateBox>
        )
      }
      footerEnd={
        setUpError ? (
          <button type="button" className="af-btn af-btn-primary af-btn-lg" onClick={onRetrySetUp}>
            Try again
          </button>
        ) : (
          <button type="button" className="af-btn af-btn-primary af-btn-lg" disabled>
            Open in Telegram
          </button>
        )
      }
    />
  );
}

// idle: a link is ready to open. waiting: opened, polling for Start.
type Phase = "idle" | "waiting";

function TelegramLinking({
  email,
  creditUsd,
  botUsername,
  agentName,
  agent,
  onContinue,
  isContinuing,
  onSkip,
  isSkipping,
  finishError,
}: TelegramStepProps & { agent: { id: string; connectionId: string } }) {
  const queryClient = useQueryClient();
  const { selectedOrganization } = useOrganizationContext();
  const [phase, setPhase] = useState<Phase>("idle");
  // The link opened last ran out before anyone pressed Start; a fresh one is showing.
  const [expired, setExpired] = useState(false);
  const [copied, setCopied] = useState(false);
  const { createLink } = useTelegramAccountLinkingActions(agent.id, agent.connectionId);
  const pending = createLink.data?.url ? { id: createLink.data.id, url: createLink.data.url } : null;
  const { linkStatus } = useTelegramLinkStatus(
    agent.id,
    agent.connectionId,
    pending?.id ?? null,
  );
  const { linkedAccounts, isLoadingLinkedAccounts } = useTelegramLinkedAccounts(agent.id, agent.connectionId, {
    whileLinking: !!pending,
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
      queryKey: telegramLinkTokenKey.detail(`${selectedOrganization?.id ?? ""}:${agent.connectionId}:${expiredTokenId}`),
    });
    newLink(() => {
      setPhase("idle");
      setExpired(true);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- once per expired link
  }, [expiredTokenId]);

  let status: React.ReactNode;
  let footerEnd: React.ReactNode;
  if (linked) {
    status = (
      <StateBox ok>
        <p className="m-0 flex items-center gap-2 text-[14px] font-semibold" style={{ color: "var(--ok)" }}>
          <Check width={16} height={16} strokeWidth={2.5} aria-hidden />
          Linked as {linkedUsername ? `@${linkedUsername}` : "your Telegram account"}
        </p>
        <Hint ok>{agentName} has sent you a welcome message.</Hint>
      </StateBox>
    );
    footerEnd = (
      <button
        type="button"
        className="af-btn af-btn-primary af-btn-lg"
        disabled={isContinuing || isSkipping}
        onClick={() => onContinue(linkedUsername ?? null)}
      >
        Continue
        <ArrowRight aria-hidden />
      </button>
    );
  } else if (createLink.isError) {
    status = <StepAlert>We couldn&apos;t create a Telegram link. Try again.</StepAlert>;
    footerEnd = (
      <button type="button" className="af-btn af-btn-primary af-btn-lg" onClick={() => newLink()}>
        Try again
      </button>
    );
  } else if (pending === null) {
    status = (
      <StateBox>
        <StepStatus>Preparing your link…</StepStatus>
      </StateBox>
    );
    footerEnd = (
      <button type="button" className="af-btn af-btn-primary af-btn-lg" disabled>
        Open in Telegram
      </button>
    );
  } else {
    status = (
      <>
        {expired && <StepAlert>That link expired after 10 minutes. Here&apos;s a fresh one.</StepAlert>}
        <StateBox>
          {phase === "waiting" ? (
            <>
              <StepStatus>Waiting for you to press Start in Telegram…</StepStatus>
              <Hint>This page updates by itself.</Hint>
            </>
          ) : (
            <>
              <p className="m-0 flex items-center gap-2 text-[13.5px]" style={{ color: "var(--ink-2)" }}>
                <span aria-hidden className="size-[7px] rounded-full" style={{ background: "var(--ok)" }} />
                {agentName} is running
              </p>
              <Hint>Open the bot to link your Telegram account.</Hint>
            </>
          )}
        </StateBox>
        <div>
          <button
            type="button"
            className="af-btn af-btn-ghost af-btn-sm -ml-2.5"
            onClick={() => {
              void navigator.clipboard.writeText(pending.url).then(() => {
                setCopied(true);
                setTimeout(() => setCopied(false), 1600);
              });
            }}
          >
            {copied ? <Check aria-hidden /> : <Copy aria-hidden />}
            {copied ? "Link copied" : "Copy link"}
          </button>
        </div>
      </>
    );
    footerEnd = (
      <a
        href={pending.url}
        target="_blank"
        rel="noreferrer"
        className={`af-btn af-btn-lg ${phase === "waiting" ? "" : "af-btn-primary"}`}
        onClick={() => {
          setPhase("waiting");
          setExpired(false);
        }}
      >
        {phase === "waiting" || expired ? "Open in Telegram again" : "Open in Telegram"}
      </a>
    );
  }

  return (
    <TelegramShell
      email={email}
      creditUsd={creditUsd}
      botUsername={botUsername}
      link={linked ? null : pending?.url ?? null}
      status={
        <>
          {status}
          {finishError && <StepAlert>We couldn&apos;t save your progress. Try again.</StepAlert>}
        </>
      }
      footerStart={linked ? undefined : <SkipLink onSkip={onSkip} isSkipping={isSkipping || isContinuing} />}
      footerEnd={footerEnd}
    />
  );
}
