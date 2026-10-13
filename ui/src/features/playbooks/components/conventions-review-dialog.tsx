"use client";

import { useState } from "react";
import Link from "next/link";
import { Loader2 } from "lucide-react";

import { AppErrorState } from "@/components/app-error-state";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useOrganizationContext } from "@/features/organizations/providers/organization-provider";
import { useTemplateLineages } from "@/features/templates/hooks/use-template-lineages";

import { usePlaybookRun } from "../hooks/use-agent-playbook-runs";
import { useAddConventionsToTemplates, type TemplateConventionsResult } from "../hooks/use-add-conventions";
import type { PlaybookConvention } from "../schemas";

type DraftRule = { text: string; selected: boolean; conversations: number };

function ConventionsForm({
  conventions,
  onDone,
}: {
  conventions: PlaybookConvention[];
  onDone: () => void;
}) {
  const { selectedOrganization } = useOrganizationContext();
  const { lineages, isLoading, error } = useTemplateLineages({ kind: "organization" });
  const add = useAddConventionsToTemplates();
  const [rules, setRules] = useState<DraftRule[]>(() =>
    conventions.map((convention) => ({ text: convention.rule, selected: true, conversations: convention.conversations })),
  );
  const [templateKeys, setTemplateKeys] = useState<Set<string>>(new Set());
  const [results, setResults] = useState<TemplateConventionsResult[] | null>(null);

  const chosenRules = rules.filter((rule) => rule.selected && rule.text.trim()).map((rule) => rule.text.trim());
  const nameOf = (key: string) => lineages.find((lineage) => lineage.templateKey === key)?.templateName ?? key;

  function updateRule(index: number, change: Partial<DraftRule>) {
    setRules((current) => current.map((rule, position) => (position === index ? { ...rule, ...change } : rule)));
  }

  function toggleTemplate(key: string, checked: boolean) {
    setTemplateKeys((current) => {
      const next = new Set(current);
      if (checked) next.add(key);
      else next.delete(key);
      return next;
    });
  }

  async function apply() {
    setResults(await add.mutateAsync({ rules: chosenRules, templateKeys: [...templateKeys] }));
  }

  if (results) {
    return (
      <>
        <ul className="m-0 list-none space-y-2 p-0 text-[0.84rem]" aria-label="Results">
          {results.map((result) => (
            <li key={result.templateKey} className="flex flex-wrap items-center justify-between gap-2">
              <span style={{ color: result.ok ? "var(--ok)" : "var(--err)" }}>
                {nameOf(result.templateKey)}:{" "}
                {result.ok
                  ? `${result.added} added to the draft${result.alreadyPresent ? `, ${result.alreadyPresent} already there` : ""}`
                  : result.message}
              </span>
              {result.ok && selectedOrganization && (
                <Link
                  className="af-btn af-btn-sm"
                  href={`/dashboard/${selectedOrganization.id}/settings/templates/${result.templateKey}`}
                >
                  Open Template
                </Link>
              )}
            </li>
          ))}
        </ul>
        <p className="text-[0.8rem]" style={{ color: "var(--ink-3)" }}>
          Publish each Template draft to apply the conventions. Agents created from the new version get them; existing
          Agents move when they are switched to it.
        </p>
        <DialogFooter>
          <button type="button" className="af-btn" onClick={onDone}>
            Done
          </button>
        </DialogFooter>
      </>
    );
  }

  return (
    <>
      <fieldset className="m-0 border-0 p-0">
        <legend className="mb-2 text-sm font-medium">Conventions</legend>
        <ul className="m-0 max-h-[40vh] list-none space-y-2 overflow-auto p-0" aria-label="Conventions">
          {rules.map((rule, index) => (
            <li key={index} className="flex items-start gap-3">
              <Checkbox
                className="mt-2"
                checked={rule.selected}
                onCheckedChange={(checked) => updateRule(index, { selected: checked === true })}
                aria-label={`Include convention ${index + 1}`}
              />
              <div className="min-w-0 flex-1">
                <input
                  type="text"
                  className="af-input w-full"
                  value={rule.text}
                  maxLength={500}
                  aria-label={`Convention ${index + 1}`}
                  onChange={(event) => updateRule(index, { text: event.target.value })}
                />
                <span className="text-[0.75rem]" style={{ color: "var(--ink-4)" }}>
                  Seen in {rule.conversations} {rule.conversations === 1 ? "conversation" : "conversations"}
                </span>
              </div>
            </li>
          ))}
        </ul>
      </fieldset>

      <fieldset className="m-0 border-0 p-0">
        <legend className="mb-2 text-sm font-medium">Add to these Templates&apos; AGENTS.md</legend>
        {isLoading ? (
          <p className="text-[0.84rem]">Loading Templates…</p>
        ) : error ? (
          <AppErrorState error={error} title="Could not load Templates" />
        ) : (
          <ul className="m-0 max-h-[30vh] list-none space-y-2 overflow-auto p-0" aria-label="Templates">
            {lineages.map((lineage) => (
              <li key={lineage.templateKey}>
                <label className="flex items-center gap-3 text-[0.88rem]">
                  <Checkbox
                    checked={templateKeys.has(lineage.templateKey)}
                    onCheckedChange={(checked) => toggleTemplate(lineage.templateKey, checked === true)}
                    aria-label={lineage.templateName}
                  />
                  <span className="min-w-0 flex-1 truncate">{lineage.templateName}</span>
                  {lineage.hasDraft && (
                    <span className="text-[0.78rem]" style={{ color: "var(--ink-4)" }}>
                      Draft in progress
                    </span>
                  )}
                </label>
              </li>
            ))}
          </ul>
        )}
      </fieldset>

      <DialogFooter>
        <button type="button" className="af-btn" onClick={onDone}>
          Cancel
        </button>
        <button
          type="button"
          className="af-btn af-btn-primary"
          disabled={chosenRules.length === 0 || templateKeys.size === 0 || add.isPending}
          onClick={() => void apply()}
        >
          {add.isPending
            ? "Adding…"
            : `Add ${chosenRules.length} to ${templateKeys.size || ""} ${templateKeys.size === 1 ? "Template" : "Templates"}`}
        </button>
      </DialogFooter>
    </>
  );
}

/** Review the Organization Conventions a run proposed and add the chosen ones to Template drafts. */
export function ConventionsReviewDialog({
  agentId,
  runId,
  onClose,
}: {
  agentId: string;
  runId: string | null;
  onClose: () => void;
}) {
  const { run, isLoadingRun, runError } = usePlaybookRun(agentId, runId);
  return (
    <Dialog open={runId !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>Organization conventions</DialogTitle>
          <DialogDescription>
            Rules this Agent follows that apply to every Agent here, whatever its role. Edit or untick any that
            don&apos;t, then add the rest to the AGENTS.md of the Templates you choose.
          </DialogDescription>
        </DialogHeader>
        {isLoadingRun ? (
          <Loader2 size={16} className="animate-spin" aria-label="Loading conventions" />
        ) : runError ? (
          <AppErrorState error={runError} title="Could not load the conventions" />
        ) : run && run.conventions.length > 0 ? (
          <ConventionsForm key={run.id} conventions={run.conventions} onDone={onClose} />
        ) : (
          <p className="text-[0.84rem]">This run proposed no organization conventions.</p>
        )}
      </DialogContent>
    </Dialog>
  );
}
