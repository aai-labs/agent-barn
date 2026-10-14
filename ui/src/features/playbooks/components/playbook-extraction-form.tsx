"use client";

import { useMemo, useState } from "react";
import { Loader2, Sparkles } from "lucide-react";

import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { Agent } from "@/features/agents/schemas";
import { formatModelLabel, formatTokens } from "@/features/costs/format";
import { getErrorDisplay } from "@/shared/api/error/get-error-display";
import { toastError } from "@/shared/toast";

import { usePlaybookPreview } from "../hooks/use-agent-playbook-runs";
import { useOrganizationPlaybookRuns } from "../hooks/use-organization-playbook-runs";
import { useStartPlaybookExtraction } from "../hooks/use-playbook-run-actions";
import { MAX_SESSION_OPTIONS, WINDOW_DAY_OPTIONS } from "../utils";

type Target = "new" | "existing";

/** The playbooks this Organization's runs have written to, newest first, one per Skill. */
function usePlaybookTargets() {
  const { runs } = useOrganizationPlaybookRuns(null, true);
  return useMemo(() => {
    const seen = new Map<string, string>();
    for (const run of runs) {
      if (run.skillId && run.status === "SUCCEEDED" && !seen.has(run.skillId)) seen.set(run.skillId, run.skillName);
    }
    return [...seen].map(([id, name]) => ({ id, name }));
  }, [runs]);
}

export function PlaybookExtractionForm({ agent, hasActiveRun }: { agent: Agent; hasActiveRun: boolean }) {
  const targets = usePlaybookTargets();
  const [target, setTarget] = useState<Target>("new");
  const [name, setName] = useState(`${agent.name} playbook`);
  const [skillId, setSkillId] = useState<string | null>(null);
  const [windowDays, setWindowDays] = useState<number>(30);
  const [maxSessions, setMaxSessions] = useState<number>(20);
  const { preview, isLoadingPreview, previewError, refetchPreview } = usePlaybookPreview(
    agent.id,
    windowDays,
    maxSessions,
    true,
  );
  const start = useStartPlaybookExtraction(agent.id);

  const chosenSkillId = skillId ?? targets[0]?.id ?? null;
  const targetReady = target === "new" ? name.trim().length > 0 : chosenSkillId !== null;
  const blockedReason = hasActiveRun
    ? "A playbook extraction is already running for this Agent."
    : preview?.sessionCount === 0
      ? "There are no conversations in this period."
      : null;

  async function submit() {
    try {
      await start.mutateAsync(
        target === "new"
          ? { skillName: name.trim(), windowDays, maxSessions }
          : { skillId: chosenSkillId!, windowDays, maxSessions },
      );
    } catch (caught) {
      toastError(caught);
    }
  }

  return (
    <section className="af-card p-5" aria-label="Create a playbook">
      <div className="flex items-start gap-3">
        <Sparkles size={18} className="mt-0.5 shrink-0" style={{ color: "var(--accent-ink)" }} aria-hidden />
        <div className="min-w-0">
          <h3 className="m-0 text-[0.95rem] font-semibold">Create a playbook from this Agent</h3>
          <p className="mb-0 mt-1 text-[0.84rem] leading-relaxed" style={{ color: "var(--ink-3)" }}>
            Reads this Agent&apos;s recent conversations, tool calls, and long-term memories, and produces two things
            for you to review. Nothing is published or installed until you do.
          </p>
          <ul className="mb-0 mt-2 pl-5 text-[0.84rem] leading-relaxed" style={{ color: "var(--ink-3)" }}>
            <li>
              <strong>Role playbook</strong>: how {agent.name} does its job, saved as a Skill draft for Agents in the
              same role.
            </li>
            <li>
              <strong>Organization conventions</strong>: rules every Agent should follow whatever its role, which you
              add to the AGENTS.md of the Templates you choose.
            </li>
          </ul>
        </div>
      </div>

      <div className="mt-5 grid gap-4 sm:grid-cols-2">
        <fieldset className="m-0 border-0 p-0 sm:col-span-2">
          <legend className="mb-2 text-sm font-medium">Save the role playbook to</legend>
          <div className="flex flex-wrap gap-2" role="radiogroup" aria-label="Save the role playbook to">
            <button
              type="button"
              role="radio"
              aria-checked={target === "new"}
              className={`af-btn ${target === "new" ? "af-btn-primary" : ""}`}
              onClick={() => setTarget("new")}
            >
              A new playbook
            </button>
            <button
              type="button"
              role="radio"
              aria-checked={target === "existing"}
              className={`af-btn ${target === "existing" ? "af-btn-primary" : ""}`}
              disabled={targets.length === 0}
              title={targets.length === 0 ? "No playbooks have been created yet." : undefined}
              onClick={() => setTarget("existing")}
            >
              The next draft of a playbook
            </button>
          </div>
        </fieldset>

        {target === "new" ? (
          <label className="block sm:col-span-2">
            <span className="mb-2 block text-sm font-medium">Playbook name</span>
            <input
              type="text"
              className="af-input w-full"
              value={name}
              maxLength={255}
              onChange={(event) => setName(event.target.value)}
            />
          </label>
        ) : (
          <div className="sm:col-span-2">
            <span className="mb-2 block text-sm font-medium" id="playbook-target-label">
              Playbook
            </span>
            <Select value={chosenSkillId ?? undefined} onValueChange={setSkillId}>
              <SelectTrigger aria-labelledby="playbook-target-label" className="w-full">
                <SelectValue placeholder="Choose a playbook" />
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  {targets.map((option) => (
                    <SelectItem key={option.id} value={option.id}>
                      {option.name}
                    </SelectItem>
                  ))}
                </SelectGroup>
              </SelectContent>
            </Select>
          </div>
        )}

        <div>
          <span className="mb-2 block text-sm font-medium" id="playbook-window-label">
            Conversations from the last
          </span>
          <Select value={String(windowDays)} onValueChange={(value) => setWindowDays(Number(value))}>
            <SelectTrigger aria-labelledby="playbook-window-label" className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                {WINDOW_DAY_OPTIONS.map((days) => (
                  <SelectItem key={days} value={String(days)}>
                    {days} days
                  </SelectItem>
                ))}
              </SelectGroup>
            </SelectContent>
          </Select>
        </div>
        <div>
          <span className="mb-2 block text-sm font-medium" id="playbook-sessions-label">
            Read at most
          </span>
          <Select value={String(maxSessions)} onValueChange={(value) => setMaxSessions(Number(value))}>
            <SelectTrigger aria-labelledby="playbook-sessions-label" className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                {MAX_SESSION_OPTIONS.map((count) => (
                  <SelectItem key={count} value={String(count)}>
                    {count} conversations
                  </SelectItem>
                ))}
              </SelectGroup>
            </SelectContent>
          </Select>
        </div>
      </div>

      <div
        className="mt-5 rounded-lg border px-4 py-3 text-[0.84rem]"
        style={{ borderColor: "var(--line)", background: "var(--bg-soft)" }}
        data-testid="playbook-preview"
        aria-live="polite"
      >
        {isLoadingPreview ? (
          <span className="inline-flex items-center gap-2" style={{ color: "var(--ink-3)" }}>
            <Loader2 size={14} className="animate-spin" aria-hidden /> Checking what this would read…
          </span>
        ) : previewError ? (
          <span role="alert">
            {getErrorDisplay(previewError).description}{" "}
            <button type="button" className="af-btn af-btn-sm" onClick={() => void refetchPreview()}>
              Retry
            </button>
          </span>
        ) : preview ? (
          <>
            <div>
              Reads <strong>{preview.sessionCount} conversations</strong> ({preview.messageCount} messages,{" "}
              {preview.toolCallCount} tool calls).
            </div>
            <div className="mt-1" style={{ color: "var(--ink-3)" }}>
              About {formatTokens(preview.estimatedInputTokens)} input and{" "}
              {formatTokens(preview.estimatedOutputTokens)} output tokens with {formatModelLabel(preview.model)},
              billed to this Agent.
            </div>
          </>
        ) : null}
      </div>

      <footer className="mt-4 flex flex-wrap items-center justify-end gap-3">
        {blockedReason && (
          <span className="text-[0.8rem]" style={{ color: "var(--ink-3)" }}>
            {blockedReason}
          </span>
        )}
        <button
          type="button"
          className="af-btn af-btn-primary"
          disabled={!targetReady || blockedReason !== null || !preview || start.isPending}
          onClick={() => void submit()}
        >
          {start.isPending ? "Starting…" : "Create playbook"}
        </button>
      </footer>
    </section>
  );
}
