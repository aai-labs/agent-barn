"use client";

import { formatUsd } from "@/features/organizations/spend-limit";

import { StepHeading } from "./onboarding-shell";

type SummaryRow = { key: string; label: string; value: string; note: string };

/** Step 3: the Agent is live; carry on in Telegram or look around the dashboard. */
export function DoneStep({
  email,
  telegramUsername,
  creditUsd,
  botUsername,
  onDashboard,
}: {
  email: string;
  telegramUsername: string | null;
  creditUsd: number | null;
  botUsername: string | null;
  onDashboard: () => void;
}) {
  const rows: SummaryRow[] = [
    { key: "account", label: "Account", value: email, note: "Google" },
    {
      key: "telegram",
      label: "Telegram",
      value: telegramUsername ? `@${telegramUsername}` : "Your account",
      note: "Linked",
    },
    ...(creditUsd != null
      ? [{ key: "credit", label: "Credit", value: `${formatUsd(creditUsd)} free`, note: "Trial" }]
      : []),
  ];

  return (
    <>
      <StepHeading title="Your agent is live in Telegram.">
        It has already sent you a message. Reply there to get started. The dashboard shows what it does and
        what it spends.
      </StepHeading>
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
      <div className="flex flex-wrap gap-3">
        {botUsername && (
          <a
            href={`https://t.me/${botUsername}`}
            target="_blank"
            rel="noreferrer"
            className="af-btn af-btn-primary af-btn-lg"
          >
            Open Telegram
          </a>
        )}
        <button type="button" className="af-btn af-btn-lg" onClick={onDashboard}>
          Go to dashboard
        </button>
      </div>
    </>
  );
}
