"use client";

import { useState } from "react";
import { Loader2, Smartphone } from "lucide-react";
import { QRCodeSVG } from "qrcode.react";

import { ConfirmationDialog } from "@/components/confirmation-dialog";

import { useWhatsAppPairing, type WhatsAppPairingState } from "../hooks/use-whatsapp-pairing";
import { whatsAppReach } from "../whatsapp";

function PairingBody({ state, restartAfterLink }: { state: WhatsAppPairingState; restartAfterLink: boolean }) {
  switch (state.phase) {
    case "scan":
      return (
        <div className="mt-4 flex flex-col items-center gap-3">
          <div className="rounded-xl bg-white p-3">
            {"image" in state.qr ? (
              // A data URL from the Agent's own gateway; next/image adds nothing here.
              // eslint-disable-next-line @next/next/no-img-element
              <img src={state.qr.image} width={208} height={208} alt="QR code that links the phone" />
            ) : (
              <QRCodeSVG value={state.qr.text} size={208} fgColor="#1a1815" aria-label="QR code that links the phone" />
            )}
          </div>
          <p className="m-0 text-center text-xs" style={{ color: "var(--ink-3)" }}>
            The code refreshes every 20 seconds. Keep this open until the phone says it is linked.
          </p>
        </div>
      );
    case "replace":
      return (
        <p className="mt-4 mb-0 text-sm" role="status" style={{ color: "var(--ink-2)" }}>
          {state.phone ?? "A phone"} is linked to this Agent now. Linking a new phone unlinks it straight away, and
          the Agent stops answering on WhatsApp until the new one is scanned.
        </p>
      );
    case "linked":
      return (
        <p className="mt-4 mb-0 text-sm" role="status" style={{ color: "var(--ink-2)" }}>
          {state.phone ? `${state.phone} is linked.` : "The phone is linked."}{" "}
          {restartAfterLink ? "Restart the Agent to start answering on WhatsApp." : "The Agent answers on WhatsApp now."}
        </p>
      );
    case "expired":
      return (
        <p className="mt-4 mb-0 text-sm" role="status" style={{ color: "var(--ink-2)" }}>
          The QR code expired before it was scanned.
        </p>
      );
    case "failed":
      return (
        <p className="mt-4 mb-0 text-sm" role="alert" style={{ color: "var(--err)" }}>
          {state.message}
        </p>
      );
    default:
      return (
        <p className="mt-4 mb-0 flex items-center gap-2 text-sm" role="status" style={{ color: "var(--ink-3)" }}>
          <Loader2 size={14} className="animate-spin" aria-hidden="true" />
          {state.phase === "connecting"
            ? `Linking ${state.phone ?? "the phone"}…`
            : "Asking the Agent for a QR code…"}
        </p>
      );
  }
}

/** Links the WhatsApp number this Agent answers as, by scanning a QR code from the phone. */
export function WhatsAppPhoneLinking({
  agentId,
  connectionId,
  linked,
  relinkNote,
  restartAfterLink,
  agentRunning,
  canManage,
  restarts,
  onRestart,
}: {
  agentId: string;
  connectionId: string;
  /** Whether a phone is linked, or null when the runtime doesn't report it (OpenClaw). */
  linked: boolean | null;
  /** What linking again does to the phone linked now, where the runtime doesn't ask first. */
  relinkNote: string | null;
  /** Whether the Agent must restart to answer on a newly linked phone. */
  restartAfterLink: boolean;
  agentRunning: boolean;
  canManage: boolean;
  /** Whether this person can restart the Agent. */
  restarts: boolean;
  onRestart: () => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const [restarting, setRestarting] = useState(false);
  const { state, start, cancel } = useWhatsAppPairing(agentId, connectionId);
  const retry = state.phase === "expired" || state.phase === "failed";
  const linkedPhase = state.phase === "linked";
  const confirmLabel =
    state.phase === "replace"
      ? "Unlink it and link a new phone"
      : linkedPhase
        ? restartAfterLink
          ? "Restart Agent"
          : "Done"
        : retry
          ? "Try again"
          : "Waiting for scan…";

  function close() {
    cancel();
    setOpen(false);
  }

  return (
    <div className="mt-2 flex flex-wrap items-center gap-2 text-xs" style={{ color: "var(--ink-3)" }}>
      <span>
        {linked === false
          ? "No phone is linked yet."
          : linked
            ? "Link a phone again if WhatsApp unlinked it or you changed numbers."
            : "Link the phone this Agent answers as, or link again to change it."}
      </span>
      {canManage && (
        <button
          type="button"
          className="af-btn af-btn-sm flex-shrink-0"
          disabled={!agentRunning}
          title={agentRunning ? undefined : "Start the Agent to link a phone"}
          onClick={() => {
            setOpen(true);
            void start();
          }}
        >
          {linked ? "Link again" : "Link phone"}
        </button>
      )}
      {canManage && !agentRunning && <span>Start the Agent to link a phone.</span>}

      <ConfirmationDialog
        open={open}
        onOpenChange={(next) => {
          if (!next) close();
        }}
        icon={<Smartphone size={18} />}
        title="Link a WhatsApp phone"
        description={
          "On the phone with the Agent's number, open WhatsApp → Settings → Linked devices → Link a device, then scan this code." +
          (linked === false || !relinkNote ? "" : ` ${relinkNote}`)
        }
        cancelLabel={
          state.phase === "replace" ? "Keep it" : linkedPhase ? (restartAfterLink ? "Restart later" : "Close") : "Cancel"
        }
        confirmLabel={confirmLabel}
        variant={state.phase === "replace" ? "destructive" : "default"}
        pendingLabel="Restarting…"
        isPending={restarting}
        confirmDisabled={linkedPhase ? restartAfterLink && !restarts : !retry && state.phase !== "replace"}
        onConfirm={async () => {
          if (retry || state.phase === "replace") {
            void start(state.phase === "replace");
            return;
          }
          if (!restartAfterLink) {
            close();
            return;
          }
          setRestarting(true);
          try {
            await onRestart();
            close();
          } finally {
            setRestarting(false);
          }
        }}
      >
        <PairingBody state={state} restartAfterLink={restartAfterLink} />
      </ConfirmationDialog>
    </div>
  );
}

/** How to talk to the Agent on WhatsApp, in the Connection's current mode and access. */
export function WhatsAppReach({ settings }: { settings: Record<string, unknown> }) {
  const reach = whatsAppReach(settings);
  return (
    <section
      aria-label={reach.title}
      className="mt-2 rounded-lg px-3 py-2.5 text-xs"
      style={{ background: "var(--bg-soft)", color: "var(--ink-2)" }}
    >
      <h4 className="m-0 text-xs font-semibold" style={{ color: "var(--ink)" }}>
        {reach.title}
      </h4>
      <ul className="m-0 mt-1.5 flex list-disc flex-col gap-1 pl-4">
        {reach.lines.map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ul>
    </section>
  );
}
