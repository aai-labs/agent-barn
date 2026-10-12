"use client";

import { useState } from "react";
import { Copy } from "lucide-react";
import { toast } from "sonner";

import { ConfirmationDialog } from "@/components/confirmation-dialog";
import {
  useTelegramAccountLinkingActions,
  useTelegramLinkedAccounts,
  useTelegramLinkStatus,
} from "@/features/communication-connections/hooks/use-telegram-account-linking";
import type { TelegramLinkedAccount } from "@/features/communication-connections/schemas";

type PendingLink = { id: string; url: string };

function accountName(account: TelegramLinkedAccount) {
  return account.telegramUsername ? `@${account.telegramUsername}` : "Telegram account";
}

/** People link their own Telegram account to this Agent, then talk to it in a private chat. */
export function TelegramAccountLinking({
  agentId,
  connectionId,
  enabled,
  canManage,
}: {
  agentId: string;
  connectionId: string;
  enabled: boolean;
  canManage: boolean;
}) {
  const [pending, setPending] = useState<PendingLink | null>(null);
  const [unlinking, setUnlinking] = useState<TelegramLinkedAccount | null>(null);
  const [error, setError] = useState<string | null>(null);
  const { linkStatus } = useTelegramLinkStatus(agentId, connectionId, pending?.id ?? null);
  const waiting = pending !== null && (linkStatus === undefined || linkStatus.status === "waiting");
  const { linkedAccounts, error: linkedAccountsError } = useTelegramLinkedAccounts(agentId, connectionId, { whileLinking: waiting });
  const { createLink, unlink } = useTelegramAccountLinkingActions(agentId, connectionId);

  function startLinking() {
    setError(null);
    createLink.mutate(undefined, {
      onSuccess: (link) => {
        if (link.url) setPending({ id: link.id, url: link.url });
      },
      onError: (cause) => setError(cause instanceof Error ? cause.message : "Could not create a link."),
    });
  }

  return (
    <div className="mt-2 flex flex-col gap-2 text-xs" style={{ color: "var(--ink-3)" }}>
      {linkedAccounts.length > 0 && (
        <ul className="flex flex-col gap-1">
          {linkedAccounts.map((account) => (
            <li key={account.id} className="flex items-center gap-2" data-testid="telegram-linked-account">
              <span style={{ color: "var(--ink-2)" }}>{accountName(account)}</span>
              <span>· linked {new Date(account.createdAt).toLocaleDateString()}</span>
              {canManage && (
                <button
                  type="button"
                  className="af-btn af-btn-sm"
                  aria-label={`Unlink ${accountName(account)}`}
                  onClick={() => setUnlinking(account)}
                >
                  Unlink
                </button>
              )}
            </li>
          ))}
        </ul>
      )}

      {linkedAccountsError && (
        <span style={{ color: "var(--err)" }}>Could not load linked Telegram accounts.</span>
      )}

      {canManage && !enabled && <span>Turn this connection on to link Telegram accounts.</span>}

      {canManage && enabled && pending === null && (
        <div className="flex items-center gap-2">
          <span>Link a Telegram account to chat with this Agent there.</span>
          <button
            type="button"
            className="af-btn af-btn-sm flex-shrink-0"
            disabled={createLink.isPending}
            onClick={startLinking}
          >
            {createLink.isPending ? "Preparing…" : "Connect Telegram"}
          </button>
        </div>
      )}

      {canManage && enabled && pending !== null && (
        <div className="flex flex-wrap items-center gap-2">
          {linkStatus?.status === "linked" ? (
            <span style={{ color: "var(--ok, var(--ink-2))" }}>
              Linked as {linkStatus.telegramUsername ? `@${linkStatus.telegramUsername}` : "your Telegram account"}
            </span>
          ) : linkStatus?.status === "expired" ? (
            <>
              <span>That link expired.</span>
              <button
                type="button"
                className="af-btn af-btn-sm flex-shrink-0"
                disabled={createLink.isPending}
                onClick={startLinking}
              >
                Get a new link
              </button>
            </>
          ) : (
            <>
              <a href={pending.url} target="_blank" rel="noreferrer" className="af-btn af-btn-sm flex-shrink-0">
                Open in Telegram
              </a>
              <button
                type="button"
                className="af-btn af-btn-sm flex-shrink-0"
                aria-label="Copy link"
                title="Copy link"
                onClick={() => {
                  void navigator.clipboard.writeText(pending.url).then(() => toast.success("Link copied to clipboard"));
                }}
              >
                <Copy width={13} height={13} />
              </button>
              <span>Waiting for you to press Start in Telegram…</span>
            </>
          )}
          {linkStatus?.status === "linked" && (
            <button type="button" className="af-btn af-btn-sm flex-shrink-0" onClick={() => setPending(null)}>
              Done
            </button>
          )}
        </div>
      )}

      {error && <span style={{ color: "var(--err)" }}>{error}</span>}

      <ConfirmationDialog
        open={unlinking !== null}
        onOpenChange={(open) => {
          if (!open) setUnlinking(null);
        }}
        title={`Unlink ${unlinking ? accountName(unlinking) : "this account"}?`}
        description="This Agent stops replying to that Telegram account until it is linked again."
        confirmLabel="Unlink"
        pendingLabel="Unlinking…"
        variant="destructive"
        isPending={unlink.isPending}
        onConfirm={async () => {
          if (!unlinking) return;
          setError(null);
          try {
            await unlink.mutateAsync(unlinking.id);
          } catch {
            setError(`Could not unlink ${accountName(unlinking)}. Try again.`);
          }
          setUnlinking(null);
        }}
      />
    </div>
  );
}
