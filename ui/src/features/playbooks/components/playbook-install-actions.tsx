"use client";

import { useState } from "react";
import Link from "next/link";
import { FileCode2, UserPlus } from "lucide-react";

import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useAgents } from "@/features/agents/hooks/use-agents";
import type { Agent } from "@/features/agents/schemas";
import { canAgent } from "@/features/agents/utils";
import { useOrganizationContext } from "@/features/organizations/providers/organization-provider";
import { useTemplateLineages } from "@/features/templates/hooks/use-template-lineages";
import { getErrorDisplay } from "@/shared/api/error/get-error-display";

import {
  useAddPlaybookToAgents,
  useRequirePlaybookOnTemplate,
  type AgentInstallResult,
} from "../hooks/use-install-playbook";

type Props = { skillId: string; skillName: string; version: number };

function pinnedVersion(agent: Agent, skillId: string): number | null {
  return agent.skills.find((skill) => skill.id === skillId)?.version ?? null;
}

function AddToAgentsDialog({ skillId, skillName, version, open, onClose }: Props & { open: boolean; onClose: () => void }) {
  const { agents, isLoading, error } = useAgents();
  const add = useAddPlaybookToAgents(skillId, version);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [results, setResults] = useState<AgentInstallResult[] | null>(null);
  const editable = agents.filter((agent) => canAgent(agent, "agent.update"));

  function toggle(agentId: string, checked: boolean) {
    setSelected((current) => {
      const next = new Set(current);
      if (checked) next.add(agentId);
      else next.delete(agentId);
      return next;
    });
  }

  async function apply() {
    setResults(await add.mutateAsync(editable.filter((agent) => selected.has(agent.id))));
    setSelected(new Set());
  }

  function close() {
    setResults(null);
    setSelected(new Set());
    onClose();
  }

  const nameOf = (agentId: string) => agents.find((agent) => agent.id === agentId)?.name ?? "Agent";
  const restartNeeded = results?.some(
    (result) => result.ok && agents.find((agent) => agent.id === result.agentId)?.status === "RUNNING",
  );

  return (
    <Dialog open={open} onOpenChange={(next) => !next && close()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add {skillName} to Agents</DialogTitle>
          <DialogDescription>
            Agents get version {version}. Agents that already have an older version move to this one.
          </DialogDescription>
        </DialogHeader>
        {results ? (
          <ul className="m-0 list-none space-y-1 p-0 text-[0.84rem]" aria-label="Results">
            {results.map((result) => (
              <li key={result.agentId} style={{ color: result.ok ? "var(--ok)" : "var(--err)" }}>
                {nameOf(result.agentId)}: {result.ok ? `now on version ${version}` : result.message}
              </li>
            ))}
            {restartNeeded && (
              <li className="pt-2" style={{ color: "var(--ink-3)" }}>
                Running Agents load the playbook the next time they restart.
              </li>
            )}
          </ul>
        ) : isLoading ? (
          <p className="text-[0.84rem]">Loading Agents…</p>
        ) : error ? (
          <p role="alert" className="text-[0.84rem]" style={{ color: "var(--err)" }}>
            {getErrorDisplay(error).description}
          </p>
        ) : editable.length === 0 ? (
          <p className="text-[0.84rem]" style={{ color: "var(--ink-3)" }}>
            You can&apos;t change the Skills of any Agent.
          </p>
        ) : (
          <ul className="m-0 max-h-[50vh] list-none space-y-2 overflow-auto p-0" aria-label="Agents">
            {editable.map((agent) => {
              const pinned = pinnedVersion(agent, skillId);
              const current = pinned === version;
              return (
                <li key={agent.id}>
                  <label className="flex items-center gap-3 text-[0.88rem]">
                    <Checkbox
                      checked={selected.has(agent.id)}
                      disabled={current}
                      onCheckedChange={(checked) => toggle(agent.id, checked === true)}
                      aria-label={agent.name}
                    />
                    <span className="min-w-0 flex-1 truncate">{agent.name}</span>
                    <span className="text-[0.78rem]" style={{ color: "var(--ink-4)" }}>
                      {current ? "Has this version" : pinned !== null ? `Has version ${pinned}` : ""}
                    </span>
                  </label>
                </li>
              );
            })}
          </ul>
        )}
        <DialogFooter>
          {results ? (
            <button type="button" className="af-btn" onClick={close}>
              Done
            </button>
          ) : (
            <>
              <button type="button" className="af-btn" onClick={close}>
                Cancel
              </button>
              <button
                type="button"
                className="af-btn af-btn-primary"
                disabled={selected.size === 0 || add.isPending}
                onClick={() => void apply()}
              >
                {add.isPending ? "Adding…" : `Add to ${selected.size || ""} ${selected.size === 1 ? "Agent" : "Agents"}`}
              </button>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function RequireOnTemplateDialog({
  skillId,
  skillName,
  version,
  open,
  onClose,
}: Props & { open: boolean; onClose: () => void }) {
  const { selectedOrganization } = useOrganizationContext();
  const { lineages, isLoading, error } = useTemplateLineages({ kind: "organization" }, open);
  const require = useRequirePlaybookOnTemplate(skillId, version);
  const [templateKey, setTemplateKey] = useState<string | null>(null);

  function close() {
    require.reset();
    setTemplateKey(null);
    onClose();
  }

  const done = require.data;
  const templateName = lineages.find((lineage) => lineage.templateKey === done?.templateKey)?.templateName;

  return (
    <Dialog open={open} onOpenChange={(next) => !next && close()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Require {skillName} on a Template</DialogTitle>
          <DialogDescription>
            Adds version {version} to the Template&apos;s draft. Agents created from the next published version get the
            playbook; existing Agents keep their Skills.
          </DialogDescription>
        </DialogHeader>
        {done ? (
          <p className="text-[0.88rem]" role="status">
            {done.alreadyRequired
              ? `${templateName ?? "The Template"}'s draft already requires this playbook.`
              : `Added to the draft of ${templateName ?? "the Template"}. Review and publish it to apply it to new Agents.`}
          </p>
        ) : isLoading ? (
          <p className="text-[0.84rem]">Loading Templates…</p>
        ) : error ? (
          <p role="alert" className="text-[0.84rem]" style={{ color: "var(--err)" }}>
            {getErrorDisplay(error).description}
          </p>
        ) : (
          <div>
            <span className="mb-2 block text-sm font-medium" id="playbook-template-label">
              Template
            </span>
            <Select value={templateKey ?? undefined} onValueChange={setTemplateKey}>
              <SelectTrigger aria-labelledby="playbook-template-label" className="w-full">
                <SelectValue placeholder="Choose a Template" />
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  {lineages.map((lineage) => (
                    <SelectItem key={lineage.templateKey} value={lineage.templateKey}>
                      {lineage.templateName}
                      {lineage.hasDraft ? " (draft in progress)" : ""}
                    </SelectItem>
                  ))}
                </SelectGroup>
              </SelectContent>
            </Select>
            {require.error && (
              <p role="alert" className="mt-2 text-[0.84rem]" style={{ color: "var(--err)" }}>
                {getErrorDisplay(require.error).description}
              </p>
            )}
          </div>
        )}
        <DialogFooter>
          {done ? (
            <>
              <button type="button" className="af-btn" onClick={close}>
                Done
              </button>
              {selectedOrganization && (
                <Link
                  className="af-btn af-btn-primary"
                  href={`/dashboard/${selectedOrganization.id}/settings/templates/${done.templateKey}`}
                >
                  Open Template
                </Link>
              )}
            </>
          ) : (
            <>
              <button type="button" className="af-btn" onClick={close}>
                Cancel
              </button>
              <button
                type="button"
                className="af-btn af-btn-primary"
                disabled={templateKey === null || require.isPending}
                onClick={() => templateKey && require.mutate(templateKey)}
              >
                {require.isPending ? "Adding…" : "Add to draft"}
              </button>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** Ways to put a published playbook to work: on existing Agents, or on new ones through a Template. */
export function PlaybookInstallActions(props: Props) {
  const [dialog, setDialog] = useState<"agents" | "template" | null>(null);
  return (
    <div className="mt-3 flex flex-wrap gap-2">
      <button type="button" className="af-btn af-btn-sm" onClick={() => setDialog("agents")}>
        <UserPlus size={13} aria-hidden /> Add to Agents
      </button>
      <button type="button" className="af-btn af-btn-sm" onClick={() => setDialog("template")}>
        <FileCode2 size={13} aria-hidden /> Require on a Template
      </button>
      {dialog === "agents" && <AddToAgentsDialog {...props} open onClose={() => setDialog(null)} />}
      {dialog === "template" && <RequireOnTemplateDialog {...props} open onClose={() => setDialog(null)} />}
    </div>
  );
}
