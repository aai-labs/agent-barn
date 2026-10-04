"use client";

import { useState } from "react";

import { AppErrorState } from "@/components/app-error-state";
import { ConfirmationDialog } from "@/components/confirmation-dialog";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { formatDate } from "@/shared/date";
import { toastError } from "@/shared/toast";

import { useCreateMemoryGrant, useRevokeMemoryGrant } from "../hooks/use-memory-grant-actions";
import { useMemoryAgentOptions, useMemoryGrants } from "../hooks/use-memory-grants";
import type { MemoryGrant } from "../schemas";
import { ORGANIZATION_MEMORY_LABEL, grantSourceLabel } from "../utils";

const ORGANIZATION_MEMORY_VALUE = "__organization__";

function sentence(grant: MemoryGrant) {
  return grant.sourceAgentId === null
    ? `${grant.agentName} can read and write ${ORGANIZATION_MEMORY_LABEL}`
    : `${grant.agentName} can read ${grantSourceLabel(grant)}'s private memories`;
}

/**
 * Directional machine access between Agents' memories. Only people with
 * `memory.access.manage` (Organization Owners and Admins) see it, and nothing here is
 * requested for anyone else: the parent passes `canManage` into every query's `enabled`.
 */
export function MemoryAccessPanel({ canManage }: { canManage: boolean }) {
  const grantsQuery = useMemoryGrants(canManage);
  const options = useMemoryAgentOptions(canManage);
  const createGrant = useCreateMemoryGrant();
  const revokeGrant = useRevokeMemoryGrant();
  const [readerId, setReaderId] = useState("");
  const [sourceId, setSourceId] = useState("");
  const [revokeTarget, setRevokeTarget] = useState<MemoryGrant | null>(null);

  if (!canManage) return null;

  const { grants } = grantsQuery;
  const sourceKey = sourceId === ORGANIZATION_MEMORY_VALUE ? null : sourceId;
  const alreadyGranted =
    readerId !== "" &&
    sourceId !== "" &&
    grants.some((grant) => grant.agentId === readerId && grant.sourceAgentId === sourceKey);
  const canSubmit = readerId !== "" && sourceId !== "" && !alreadyGranted && !createGrant.isPending;
  const sourceAgents = options.agents.filter((agent) => agent.id !== readerId);

  async function submit() {
    try {
      await createGrant.mutateAsync({ agentId: readerId, sourceAgentId: sourceKey ?? undefined });
      setReaderId("");
      setSourceId("");
    } catch {
      // Shown inline from createGrant.error.
    }
  }

  async function confirmRevoke() {
    if (!revokeTarget) return;
    try {
      await revokeGrant.mutateAsync(revokeTarget.id);
    } catch (error) {
      toastError(error, "Revoking access failed.");
    } finally {
      setRevokeTarget(null);
    }
  }

  return (
    <>
      <div
        className="mb-5 rounded-xl px-3.5 py-3 text-[13px] leading-[1.5]"
        style={{ background: "var(--bg-soft)", color: "var(--ink-3)" }}
      >
        Agents keep their memories private by default. A grant lets one Agent recall another Agent&apos;s private
        memories, or use {ORGANIZATION_MEMORY_LABEL}: memories shared by every Agent with that access, which they
        can both read and write. Grants work in one direction and never move or change stored memories.
      </div>

      <section className="mb-6" aria-label="Grant memory access">
        <h3 className="mb-3 mt-0 text-[0.95rem] font-semibold" style={{ color: "var(--ink)" }}>
          Grant access
        </h3>
        <div className="flex flex-wrap items-end gap-3">
          <label className="flex min-w-48 flex-1 flex-col gap-1.5 text-[0.84rem] font-medium" style={{ color: "var(--ink)" }}>
            Reader Agent
            <Select
              value={readerId}
              onValueChange={(value) => {
                setReaderId(value);
                if (value === sourceId) setSourceId("");
                createGrant.reset();
              }}
              disabled={options.isLoading || options.agents.length === 0}
            >
              <SelectTrigger aria-label="Reader Agent">
                <SelectValue placeholder="Choose an Agent" />
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  {options.agents.map((agent) => (
                    <SelectItem key={agent.id} value={agent.id}>
                      {agent.name}
                    </SelectItem>
                  ))}
                </SelectGroup>
              </SelectContent>
            </Select>
          </label>

          <label className="flex min-w-48 flex-1 flex-col gap-1.5 text-[0.84rem] font-medium" style={{ color: "var(--ink)" }}>
            Can access
            <Select
              value={sourceId}
              onValueChange={(value) => {
                setSourceId(value);
                createGrant.reset();
              }}
              disabled={options.isLoading || options.agents.length === 0}
            >
              <SelectTrigger aria-label="Memory to access">
                <SelectValue placeholder="Choose memory" />
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  <SelectLabel>Shared</SelectLabel>
                  <SelectItem value={ORGANIZATION_MEMORY_VALUE}>{ORGANIZATION_MEMORY_LABEL}</SelectItem>
                </SelectGroup>
                {sourceAgents.length > 0 && (
                  <SelectGroup>
                    <SelectLabel>Another Agent&apos;s private memories</SelectLabel>
                    {sourceAgents.map((agent) => (
                      <SelectItem key={agent.id} value={agent.id}>
                        {agent.name}
                      </SelectItem>
                    ))}
                  </SelectGroup>
                )}
              </SelectContent>
            </Select>
          </label>

          <button type="button" className="af-btn af-btn-primary" disabled={!canSubmit} onClick={() => void submit()}>
            {createGrant.isPending ? "Granting…" : "Grant access"}
          </button>
        </div>

        {alreadyGranted && (
          <p className="mb-0 mt-2 text-[0.8rem]" style={{ color: "var(--ink-3)" }}>
            That Agent already has this access.
          </p>
        )}
        {createGrant.error && (
          <p role="alert" className="mb-0 mt-2 text-[0.8rem]" style={{ color: "var(--err)" }}>
            {createGrant.error instanceof Error ? createGrant.error.message : "Granting access failed."}
          </p>
        )}
        {options.error && (
          <AppErrorState
            error={options.error}
            title="We couldn't load Agents"
            onRetry={() => {
              void options.refetch();
            }}
            retryLabel="Retry"
            className="min-h-0 p-0 pt-3"
          />
        )}
        {options.truncated && (
          <p className="mb-0 mt-2 text-[0.8rem]" style={{ color: "var(--ink-3)" }}>
            Only the first 200 Agents are listed, so some Agents cannot be chosen here.
          </p>
        )}
      </section>

      <section aria-label="Current memory access">
        <h3 className="mb-1 mt-0 text-[0.95rem] font-semibold" style={{ color: "var(--ink)" }}>
          Current access
        </h3>

        {grantsQuery.isLoading && (
          <div className="py-8 text-center text-[13px]" style={{ color: "var(--ink-3)" }}>
            Loading memory access…
          </div>
        )}
        {grantsQuery.error && (
          <AppErrorState
            error={grantsQuery.error}
            title="We couldn't load memory access"
            description="The list of memory grants is unavailable right now."
            onRetry={() => {
              void grantsQuery.refetch();
            }}
            retryLabel="Retry"
          />
        )}
        {!grantsQuery.isLoading && !grantsQuery.error && grants.length === 0 && (
          <div
            className="flex flex-col items-center justify-center rounded-2xl py-10 text-center"
            style={{ border: "1px dashed var(--line-strong)", color: "var(--ink-3)" }}
          >
            <div className="mb-1 text-[0.9375rem] font-medium" style={{ color: "var(--ink)" }}>
              No memory access granted
            </div>
            <div className="text-[0.844rem]">Every Agent can only recall its own memories.</div>
          </div>
        )}

        <ul className="m-0 list-none p-0">
          {grants.map((grant) => (
            <li
              key={grant.id}
              className="flex items-center gap-3 py-3.5"
              style={{ borderBottom: "1px solid var(--line)" }}
            >
              <div className="min-w-0 flex-1">
                <div className="text-[14px] font-medium" style={{ color: "var(--ink)" }}>
                  {sentence(grant)}
                </div>
                <div className="mt-0.5 text-[12.5px]" style={{ color: "var(--ink-3)" }}>
                  Granted {formatDate(grant.createdAt)}
                </div>
              </div>
              <button
                type="button"
                className="af-btn af-btn-sm"
                aria-label={`Revoke ${sentence(grant)}`}
                onClick={() => setRevokeTarget(grant)}
              >
                Revoke
              </button>
            </li>
          ))}
        </ul>
      </section>

      <ConfirmationDialog
        open={revokeTarget !== null}
        onOpenChange={(open) => {
          if (!open) setRevokeTarget(null);
        }}
        title="Revoke memory access?"
        description={
          revokeTarget
            ? `${revokeTarget.agentName} will stop recalling ${grantSourceLabel(revokeTarget)}${
                revokeTarget.sourceAgentId === null ? " and can no longer write to it" : ""
              } the next time it asks. Stored memories are not changed.`
            : ""
        }
        confirmLabel="Revoke access"
        pendingLabel="Revoking…"
        variant="destructive"
        isPending={revokeGrant.isPending}
        onConfirm={() => void confirmRevoke()}
      />
    </>
  );
}
