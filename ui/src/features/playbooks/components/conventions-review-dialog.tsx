"use client";

import { useState } from "react";
import Link from "next/link";
import { Loader2 } from "lucide-react";

import { AppErrorState } from "@/components/app-error-state";
import { Badge } from "@/components/badge";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";
import { useOrganizationContext } from "@/features/organizations/providers/organization-provider";
import { useTemplateLineages } from "@/features/templates/hooks/use-template-lineages";
import type { TemplateLineageSummary } from "@/features/templates/schemas";

import { usePlaybookRun } from "../hooks/use-agent-playbook-runs";
import { useAddConventionsToTemplates, type TemplateConventionsResult } from "../hooks/use-add-conventions";
import type { PlaybookConvention } from "../schemas";

type DraftRule = { text: string; selected: boolean; conversations: number };
type Step = "rules" | "templates";

function plural(count: number, one: string, many: string): string {
  return `${count} ${count === 1 ? one : many}`;
}

function RulesStep({
  rules,
  onChange,
}: {
  rules: DraftRule[];
  onChange: (index: number, change: Partial<DraftRule>) => void;
}) {
  return (
    <fieldset className="m-0 min-w-0 border-0 p-0">
      <legend className="mb-2 text-sm font-medium">Step 1 of 2 · Review the rules</legend>
      <ul className="m-0 max-h-[55vh] list-none space-y-3 overflow-auto p-0 pr-1" aria-label="Conventions">
        {rules.map((rule, index) => (
          <li key={index} className="flex items-start gap-3">
            <Checkbox
              className="mt-2.5"
              checked={rule.selected}
              onCheckedChange={(checked) => onChange(index, { selected: checked === true })}
              aria-label={`Include convention ${index + 1}`}
            />
            <div className="min-w-0 flex-1">
              <Textarea
                className="min-h-0 resize-none"
                rows={1}
                value={rule.text}
                maxLength={500}
                disabled={!rule.selected}
                aria-label={`Convention ${index + 1}`}
                onChange={(event) => onChange(index, { text: event.target.value })}
              />
              <span className="text-[0.75rem]" style={{ color: "var(--ink-4)" }}>
                Seen in {plural(rule.conversations, "conversation", "conversations")}
              </span>
            </div>
          </li>
        ))}
      </ul>
    </fieldset>
  );
}

function TemplatesStep({
  lineages,
  selected,
  onToggle,
  onSelectMany,
}: {
  lineages: TemplateLineageSummary[];
  selected: Set<string>;
  onToggle: (key: string, checked: boolean) => void;
  onSelectMany: (keys: string[], checked: boolean) => void;
}) {
  const anyInUse = lineages.some((lineage) => lineage.inUse);
  const [search, setSearch] = useState("");
  const [onlyInUse, setOnlyInUse] = useState(anyInUse);
  const term = search.trim().toLowerCase();
  // Templates Agents use first: they are where conventions take effect.
  const shown = lineages
    .filter((lineage) => (!onlyInUse || lineage.inUse) && lineage.templateName.toLowerCase().includes(term))
    .sort((a, b) => Number(!!b.inUse) - Number(!!a.inUse) || a.templateName.localeCompare(b.templateName));
  const shownKeys = shown.map((lineage) => lineage.templateKey);
  const hiddenSelected = [...selected].filter((key) => !shownKeys.includes(key)).length;

  return (
    <fieldset className="m-0 min-w-0 border-0 p-0">
      <legend className="mb-2 text-sm font-medium">Step 2 of 2 · Choose Templates</legend>
      <div className="flex flex-wrap items-center gap-3">
        <input
          type="search"
          className="af-input min-w-[12rem] flex-1"
          placeholder="Search Templates"
          aria-label="Search Templates"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
        <label className="flex items-center gap-2 text-[0.84rem]">
          <Checkbox
            checked={onlyInUse}
            disabled={!anyInUse}
            onCheckedChange={(checked) => setOnlyInUse(checked === true)}
          />
          Only Templates Agents use
        </label>
      </div>
      <div
        className="mt-3 flex flex-wrap items-center justify-between gap-2 text-[0.8rem]"
        style={{ color: "var(--ink-3)" }}
      >
        <span data-testid="selected-template-count">
          {plural(selected.size, "Template", "Templates")} selected
          {hiddenSelected > 0 ? ` (${hiddenSelected} not shown)` : ""}
        </span>
        <span className="flex gap-2">
          <button
            type="button"
            className="af-btn af-btn-sm"
            disabled={shown.length === 0}
            onClick={() => onSelectMany(shownKeys, true)}
          >
            Select all shown
          </button>
          <button
            type="button"
            className="af-btn af-btn-sm"
            disabled={selected.size === 0}
            onClick={() => onSelectMany([...selected], false)}
          >
            Clear
          </button>
        </span>
      </div>
      {shown.length === 0 ? (
        <p className="mt-3 text-[0.84rem]" style={{ color: "var(--ink-3)" }}>
          No Templates match.
        </p>
      ) : (
        <ul
          className="m-0 mt-2 max-h-[45vh] list-none overflow-auto rounded-lg border p-0"
          style={{ borderColor: "var(--line)" }}
          aria-label="Templates"
        >
          {shown.map((lineage) => {
            const version = lineage.latestPublishedVersion !== null ? `v${lineage.latestPublishedVersion}` : "unpublished";
            return (
              <li key={lineage.templateKey} className="border-b last:border-b-0" style={{ borderColor: "var(--line)" }}>
                <label className="flex cursor-pointer items-center gap-3 px-3 py-2 text-[0.88rem]">
                  <Checkbox
                    checked={selected.has(lineage.templateKey)}
                    onCheckedChange={(checked) => onToggle(lineage.templateKey, checked === true)}
                    aria-label={`${lineage.templateName} ${version}`}
                  />
                  <span className="min-w-0 flex-1 truncate">{lineage.templateName}</span>
                  <span className="flex shrink-0 items-center gap-1.5">
                    {lineage.inUse && <Badge variant="ok">In use</Badge>}
                    {lineage.templateSource === "pre-defined" && !lineage.isFork && <Badge>Built-in</Badge>}
                    {lineage.hasDraft && <Badge variant="warn">Draft in progress</Badge>}
                    <span className="font-mono text-[0.75rem]" style={{ color: "var(--ink-4)" }}>
                      {version}
                    </span>
                  </span>
                </label>
              </li>
            );
          })}
        </ul>
      )}
      {!anyInUse && (
        <p className="mb-0 mt-2 text-[0.78rem]" style={{ color: "var(--ink-4)" }}>
          No Agent uses any of these Templates yet.
        </p>
      )}
    </fieldset>
  );
}

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
  const [step, setStep] = useState<Step>("rules");
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

  function selectTemplates(keys: string[], checked: boolean) {
    setTemplateKeys((current) => {
      const next = new Set(current);
      for (const key of keys) {
        if (checked) next.add(key);
        else next.delete(key);
      }
      return next;
    });
  }

  async function apply() {
    setResults(await add.mutateAsync({ rules: chosenRules, templateKeys: [...templateKeys] }));
  }

  if (results) {
    return (
      <>
        <ul className="m-0 max-h-[55vh] list-none space-y-2 overflow-auto p-0 text-[0.84rem]" aria-label="Results">
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

  if (step === "rules") {
    return (
      <>
        <RulesStep rules={rules} onChange={updateRule} />
        <DialogFooter>
          <button type="button" className="af-btn" onClick={onDone}>
            Cancel
          </button>
          <button
            type="button"
            className="af-btn af-btn-primary"
            disabled={chosenRules.length === 0}
            onClick={() => setStep("templates")}
          >
            Next: choose Templates ({plural(chosenRules.length, "rule", "rules")})
          </button>
        </DialogFooter>
      </>
    );
  }

  return (
    <>
      {isLoading ? (
        <p className="text-[0.84rem]">Loading Templates…</p>
      ) : error ? (
        <AppErrorState error={error} title="Could not load Templates" />
      ) : (
        <TemplatesStep
          lineages={lineages}
          selected={templateKeys}
          onToggle={(key, checked) => selectTemplates([key], checked)}
          onSelectMany={selectTemplates}
        />
      )}
      <DialogFooter>
        <button type="button" className="af-btn" disabled={add.isPending} onClick={() => setStep("rules")}>
          Back
        </button>
        <button
          type="button"
          className="af-btn af-btn-primary"
          disabled={templateKeys.size === 0 || add.isPending}
          onClick={() => void apply()}
        >
          {add.isPending
            ? "Adding…"
            : `Add ${plural(chosenRules.length, "rule", "rules")} to ${plural(templateKeys.size, "Template", "Templates")}`}
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
      <DialogContent className="max-h-[90vh] max-w-2xl overflow-y-auto">
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
