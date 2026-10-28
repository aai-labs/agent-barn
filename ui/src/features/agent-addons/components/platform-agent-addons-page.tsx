"use client";

import { useState } from "react";
import { Loader2 } from "lucide-react";
import { parseAsStringEnum, useQueryState } from "nuqs";
import { toast } from "sonner";

import { AppErrorState } from "@/components/app-error-state";
import { Badge } from "@/components/badge";
import { ConfirmationDialog } from "@/components/confirmation-dialog";
import { ListPageHeader } from "@/components/list-page-header";
import { OrganizationCombobox } from "@/components/organization-combobox";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useLoadMoreOnScroll } from "@/hooks/use-load-more-on-scroll";

import { type AddonDecision, useDecidePlatformAgentAddon, usePlatformAgentAddons } from "../hooks/use-platform-agent-addons";
import { type AgentAddonState, AgentAddonStateSchema, type PlatformAgentAddon } from "../schemas";
import {
  ADDON_KIND_LABELS,
  ADDON_STATE_LABELS,
  ADDON_STATE_VARIANTS,
  addonPin,
  formatAddonDate,
} from "../utils";

const ALL = "ALL";
const RUNTIME_LABELS: Record<string, string> = { openclaw: "OpenClaw", hermes: "Hermes" };

type Deciding = { request: PlatformAgentAddon; action: AddonDecision["action"] };

/**
 * Platform → Add-ons: every add-on request across Organizations, to review.
 *
 * Each row is the request exactly as made, with where it comes from and why. A Platform
 * Administrator approves or rejects a pending one, with a reason, and revokes an approved one;
 * nobody edits a request. Nothing here restarts an Agent: a decision applies at its next start.
 * Nothing else of the Agent is shown.
 */
export function PlatformAgentAddonsPage() {
  const [stateFilter, setStateFilter] = useQueryState(
    "state",
    parseAsStringEnum<AgentAddonState | typeof ALL>([...AgentAddonStateSchema.options, ALL])
      .withDefault("PENDING")
      .withOptions({ history: "replace", scroll: false }),
  );
  const [search, setSearch] = useState("");
  const [organization, setOrganization] = useState<{ id: string; name: string } | null>(null);
  const [deciding, setDeciding] = useState<Deciding | null>(null);
  const [rejection, setRejection] = useState("");
  const decide = useDecidePlatformAgentAddon();
  const state = stateFilter === ALL ? null : stateFilter;
  const { requests, total, hasNextPage, fetchNextPage, isFetchingNextPage, isLoading, error, refetch } =
    usePlatformAgentAddons({ state, search, organizationId: organization?.id ?? null });
  const loadMoreRef = useLoadMoreOnScroll({
    hasNextPage: Boolean(hasNextPage),
    isFetchingNextPage,
    fetchNextPage: () => void fetchNextPage(),
  });

  const open = (request: PlatformAgentAddon, action: AddonDecision["action"]) => {
    decide.reset();
    setRejection("");
    setDeciding({ request, action });
  };

  return (
    <div data-testid="platform-agent-addons-page">
      <ListPageHeader
        title="Add-ons"
        description="Libraries and tools organizations asked to install on one of their agents. Review each exactly as requested."
        count={total}
        noun="request"
        onSearch={setSearch}
        searchPlaceholder="Search by add-on, agent or organization"
        action={
          <div className="flex items-center gap-2">
            <Select value={stateFilter} onValueChange={(value) => void setStateFilter(value as AgentAddonState)}>
              <SelectTrigger aria-label="State" className="w-[11rem]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  {AgentAddonStateSchema.options.map((option) => (
                    <SelectItem key={option} value={option}>
                      {ADDON_STATE_LABELS[option]}
                    </SelectItem>
                  ))}
                  <SelectItem value={ALL}>All states</SelectItem>
                </SelectGroup>
              </SelectContent>
            </Select>
            <OrganizationCombobox
              organizationId={organization?.id ?? null}
              organizationName={organization?.name ?? null}
              onChange={setOrganization}
            />
          </div>
        }
      />

      {isLoading ? (
        <p className="m-0 text-[13.5px]" style={{ color: "var(--ink-3)" }}>
          Loading requests…
        </p>
      ) : error ? (
        <AppErrorState
          error={error}
          title="We couldn't load add-on requests"
          onRetry={() => void refetch()}
          retryLabel="Retry"
          className="min-h-[240px] p-0"
        />
      ) : requests.length === 0 ? (
        <div
          className="flex flex-col items-center justify-center rounded-2xl py-16 text-center"
          style={{ border: "1px dashed var(--line-strong)" }}
        >
          <div className="mb-1 text-[15px] font-medium" style={{ color: "var(--ink)" }}>
            No requests
          </div>
          <div className="text-[13.5px]" style={{ color: "var(--ink-3)" }}>
            {state === "PENDING" ? "Nothing is waiting for review." : "Try a different filter or search."}
          </div>
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          <ul className="m-0 flex list-none flex-col gap-3 p-0">
            {requests.map((request) => (
              <RequestRow key={request.id} request={request} onDecide={(action) => open(request, action)} />
            ))}
          </ul>
          {hasNextPage && (
            <div
              ref={loadMoreRef}
              className="flex items-center justify-center gap-2 py-6 text-[13px]"
              style={{ color: "var(--ink-4)" }}
            >
              <Loader2 width={14} className={isFetchingNextPage ? "animate-spin" : "invisible"} />
              Loading more requests…
            </div>
          )}
        </div>
      )}

      {deciding && (
        <ConfirmationDialog
          open
          onOpenChange={(isOpen) => !isOpen && setDeciding(null)}
          title={
            deciding.action === "approve"
              ? `Approve ${deciding.request.name}?`
              : deciding.action === "reject"
                ? `Reject ${deciding.request.name}?`
                : `Revoke ${deciding.request.name}?`
          }
          description={
            deciding.action === "approve"
              ? `It is installed on ${deciding.request.agentName} (${deciding.request.organizationName}) the next time that agent starts, exactly as requested.`
              : deciding.action === "reject"
                ? `${deciding.request.organizationName} sees your reason and can make a new request.`
                : `${deciding.request.agentName} loses it the next time it starts. The agent keeps running until then.`
          }
          confirmLabel={deciding.action === "approve" ? "Approve" : deciding.action === "reject" ? "Reject" : "Revoke"}
          pendingLabel="Saving…"
          variant={deciding.action === "approve" ? "default" : "destructive"}
          confirmDisabled={deciding.action === "reject" && !rejection.trim()}
          isPending={decide.isPending}
          onConfirm={async () => {
            const decision: AddonDecision =
              deciding.action === "reject" ? { action: "reject", reason: rejection.trim() } : { action: deciding.action };
            try {
              const updated = await decide.mutateAsync({ addonId: deciding.request.id, decision });
              toast.success(`${updated.name} ${ADDON_STATE_LABELS[updated.state].toLowerCase()}`);
              setDeciding(null);
            } catch {
              /* The error stays in the dialog. */
            }
          }}
        >
          {deciding.action === "reject" && (
            <div className="flex flex-col gap-1.5">
              <label className="text-[0.8rem] font-medium" style={{ color: "var(--ink-2)" }} htmlFor="addon-rejection">
                Reason
              </label>
              <Textarea
                id="addon-rejection"
                className="min-h-20"
                placeholder="What the organization should know or change"
                value={rejection}
                maxLength={1000}
                onChange={(event) => setRejection(event.target.value)}
              />
            </div>
          )}
          {decide.isError && (
            <p className="m-0 text-[13px]" role="alert" style={{ color: "var(--err)" }}>
              {decide.error instanceof Error ? decide.error.message : "The decision could not be saved."}
            </p>
          )}
        </ConfirmationDialog>
      )}
    </div>
  );
}

function RequestRow({
  request,
  onDecide,
}: {
  request: PlatformAgentAddon;
  onDecide: (action: AddonDecision["action"]) => void;
}) {
  const requester = request.requestedBy ? (request.requestedBy.fullName ?? request.requestedBy.email) : "a former member";
  return (
    <li className="af-card flex flex-col gap-2 px-4 py-3.5" data-testid={`platform-addon-${request.id}`} aria-label={request.name}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[0.95rem] font-semibold" style={{ color: "var(--ink)" }}>
          {request.name}
        </span>
        <span className="text-[0.75rem]" style={{ color: "var(--ink-4)" }}>
          {ADDON_KIND_LABELS[request.kind]}
        </span>
        <Badge variant={ADDON_STATE_VARIANTS[request.state]}>{ADDON_STATE_LABELS[request.state]}</Badge>
        <div className="ml-auto flex gap-2">
          {request.state === "PENDING" && (
            <>
              <button type="button" className="af-btn af-btn-sm" onClick={() => onDecide("reject")}>
                Reject
              </button>
              <button type="button" className="af-btn af-btn-sm af-btn-primary" onClick={() => onDecide("approve")}>
                Approve
              </button>
            </>
          )}
          {request.state === "APPROVED" && (
            <button type="button" className="af-btn af-btn-sm" onClick={() => onDecide("revoke")}>
              Revoke
            </button>
          )}
        </div>
      </div>
      <div className="text-[0.8rem]" style={{ color: "var(--ink-3)" }}>
        {request.organizationName} · {request.agentName}
        {request.agentDeleted ? " (deleted)" : ""} · {RUNTIME_LABELS[request.agentType] ?? request.agentType}
      </div>
      <code
        className="block overflow-x-auto whitespace-pre-wrap break-all rounded-lg px-2.5 py-1.5 text-[0.78rem]"
        style={{ background: "var(--bg-soft)", color: "var(--ink-2)" }}
      >
        {addonPin(request.kind, request.name, request.spec)}
      </code>
      <p className="m-0 text-[0.84rem]" style={{ color: "var(--ink-2)" }}>
        <span style={{ color: "var(--ink-4)" }}>Why: </span>
        {request.reason}
      </p>
      {request.state === "REJECTED" && request.rejectionReason && (
        <p className="m-0 text-[0.84rem]" style={{ color: "var(--err)" }}>
          Rejected: {request.rejectionReason}
        </p>
      )}
      <p className="m-0 text-[0.72rem]" style={{ color: "var(--ink-4)" }}>
        Requested by {requester} {formatAddonDate(request.createdAt)}
        {request.decidedAt
          ? ` · ${ADDON_STATE_LABELS[request.state].toLowerCase()}${
              request.decidedBy ? ` by ${request.decidedBy.fullName ?? request.decidedBy.email}` : ""
            } ${formatAddonDate(request.decidedAt)}`
          : ""}
      </p>
    </li>
  );
}
