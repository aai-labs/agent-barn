"use client";

import Link from "next/link";

import { formatUsd } from "@/features/organizations/spend-limit";

import { OnboardingShell, type OnboardingPath } from "./onboarding-shell";

type SummaryRow = { key: string; label: string; value: string; note: string };

/** Step 4: the Agent is ready; choose where to chat or open the dashboard. */
export function DoneStep({
  email,
  telegramUsername,
  creditUsd,
  botUsername,
  onDashboard,
  path,
  agentName,
  chatHref,
  channelsHref,
}: {
  path: OnboardingPath;
  agentName: string;
  chatHref: string;
  channelsHref: string;
  email: string;
  telegramUsername: string | null;
  creditUsd: number | null;
  botUsername: string | null;
  onDashboard: () => void;
}) {
  const rows: SummaryRow[] = [
    { key: "account", label: "Account", value: email, note: "Google" },
    ...(path === "quick" ? [{
      key: "telegram",
      label: "Telegram",
      value: telegramUsername ? `@${telegramUsername}` : "Your account",
      note: "Linked",
    }] : [{ key: "agent", label: "Agent", value: agentName, note: "Ready" }]),
    ...(creditUsd != null
      ? [{ key: "credit", label: "Credit", value: `${formatUsd(creditUsd)} free`, note: "Trial" }]
      : []),
  ];

  return (
    <OnboardingShell
      step={3}
      path={path}
      email={email}
      creditUsd={creditUsd}
      title={path === "quick" ? "Your agent is live in Telegram." : `${agentName} is ready`}
      subtitle={path === "quick" ? "Reply in Telegram to get started. The dashboard shows what your agent does and spends." : "Chat on the web now, or connect a channel whenever you're ready."}
      footerStart={
        <button type="button" className="af-btn af-btn-lg" onClick={onDashboard}>
          Go to dashboard
        </button>
      }
      footerEnd={path === "quick" && botUsername ? (
        <a href={`https://t.me/${botUsername}`} target="_blank" rel="noreferrer" className="af-btn af-btn-primary af-btn-lg">
          Open Telegram
        </a>
      ) : (
        <Link href={chatHref} className="af-btn af-btn-primary af-btn-lg">
          Chat with your agent
        </Link>
      )}
    >
      <dl className="m-0 mb-6 flex flex-col">
        {rows.map((row) => (
          <div
            key={row.key}
            data-testid={`onboarding-summary-${row.key}`}
            className="flex items-baseline gap-3 py-2.5"
            style={{ borderTop: "1px solid var(--line)" }}
          >
            <dt className="w-20 shrink-0 text-[12.5px]" style={{ color: "var(--ink-3)" }}>
              {row.label}
            </dt>
            <dd className="m-0 min-w-0 flex-1 truncate text-[13.5px]" style={{ color: "var(--ink)" }}>
              {row.value}
            </dd>
            <dd className="m-0 text-[12px]" style={{ color: "var(--ink-4)" }}>
              {row.note}
            </dd>
          </div>
        ))}
      </dl>
      {path === "own" && <Link href={channelsHref} className="af-btn af-btn-lg">Connect a messaging app</Link>}
    </OnboardingShell>
  );
}
