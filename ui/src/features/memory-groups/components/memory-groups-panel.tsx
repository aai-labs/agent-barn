"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { Brain, Check, ChevronDownIcon, Pencil, Plus, Trash2, Users, X } from "lucide-react";
import { toast } from "sonner";

import { AppErrorState } from "@/components/app-error-state";
import { ConfirmationDialog } from "@/components/confirmation-dialog";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { useAgents } from "@/features/agents/hooks/use-agents";
import type { Agent } from "@/features/agents/schemas";
import { useActiveOrgRole } from "@/features/organizations/hooks/use-active-org-role";
import { toastError } from "@/shared/toast";

import type { MemoryGroup } from "../schemas";
import { useMemoryGroups } from "../hooks/use-memory-groups";
import { useMemoryGroupMutations } from "../hooks/use-memory-group-mutations";

export function MemoryGroupsPanel() {
  const params = useParams();
  const orgId = typeof params?.orgId === "string" ? params.orgId : "";
  const { canManage } = useActiveOrgRole();
  const { groups, isLoading, error } = useMemoryGroups();
  const { agents } = useAgents();
  const { create, rename, remove, addAgent, removeAgent } = useMemoryGroupMutations();

  const [newName, setNewName] = useState("");
  const [renaming, setRenaming] = useState<{ id: string; name: string } | null>(null);
  const [deleting, setDeleting] = useState<MemoryGroup | null>(null);

  const membersByGroup = useMemo(() => {
    const map = new Map<string, Agent[]>();
    for (const agent of agents) {
      if (!agent.memoryGroupId) continue;
      const list = map.get(agent.memoryGroupId) ?? [];
      list.push(agent);
      map.set(agent.memoryGroupId, list);
    }
    return map;
  }, [agents]);

  const onCreate = async () => {
    const name = newName.trim();
    if (!name) return;
    try {
      await create.mutateAsync({ name });
      setNewName("");
      toast.success(`Created “${name}”.`);
    } catch (err) {
      toastError(err, "Could not create the group.");
    }
  };

  const onRename = async () => {
    if (!renaming) return;
    const name = renaming.name.trim();
    if (!name) return;
    try {
      await rename.mutateAsync({ id: renaming.id, name });
      setRenaming(null);
      toast.success("Group renamed.");
    } catch (err) {
      toastError(err, "Could not rename the group.");
    }
  };

  const onDelete = async () => {
    if (!deleting) return;
    try {
      await remove.mutateAsync(deleting.id);
      toast.success(`Deleted “${deleting.name}”.`);
      setDeleting(null);
    } catch (err) {
      toastError(err, "Could not delete the group.");
    }
  };

  return (
    <div>
      <div
        className="mb-5 flex items-start gap-2 rounded-xl px-3.5 py-3 text-[13px] leading-[1.5]"
        style={{ background: "var(--bg-soft)", color: "var(--ink-3)" }}
      >
        <Users size={15} style={{ flexShrink: 0, marginTop: 1 }} aria-hidden />
        Agents in the same memory group share what they learn — each one can draw on the others&rsquo; memory. Add an
        agent to a group to turn its shared memory on; remove it to turn it off.
      </div>

      {canManage && (
        <div className="mb-4 flex items-center gap-2.5">
          <input
            className="af-input flex-1"
            placeholder="New group name…"
            aria-label="New group name"
            value={newName}
            maxLength={255}
            onChange={(e) => setNewName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") onCreate();
            }}
          />
          <button
            className="af-btn af-btn-primary whitespace-nowrap"
            onClick={onCreate}
            disabled={!newName.trim() || create.isPending}
          >
            <Plus size={15} /> Create group
          </button>
        </div>
      )}

      {isLoading && (
        <div className="py-8 text-center text-[13px]" style={{ color: "var(--ink-3)" }}>
          Loading groups…
        </div>
      )}
      {error && <AppErrorState error={error} />}

      {!isLoading && !error && groups.length === 0 && (
        <div
          className="rounded-xl border border-dashed px-4 py-10 text-center text-[13px]"
          style={{ borderColor: "var(--line)", color: "var(--ink-3)" }}
        >
          No memory groups yet.{canManage ? " Create one above to let agents share memory." : ""}
        </div>
      )}

      <div className="space-y-3">
        {groups.map((group) => {
          const members = membersByGroup.get(group.id) ?? [];
          const available = agents.filter((a) => a.memoryGroupId !== group.id);
          const isRenaming = renaming?.id === group.id;
          return (
            <div key={group.id} className="af-card p-4">
              <div className="flex items-center gap-2">
                {isRenaming ? (
                  <input
                    className="af-input flex-1"
                    value={renaming.name}
                    autoFocus
                    maxLength={255}
                    aria-label="Group name"
                    onChange={(e) => setRenaming({ id: group.id, name: e.target.value })}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") onRename();
                      if (e.key === "Escape") setRenaming(null);
                    }}
                  />
                ) : (
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-medium" style={{ color: "var(--ink)" }}>
                      {group.name}
                    </div>
                    <div className="text-[12px]" style={{ color: "var(--ink-4)" }}>
                      {members.length === 1 ? "1 agent" : `${members.length} agents`}
                    </div>
                  </div>
                )}

                {!isRenaming && (
                  <Link
                    href={`/dashboard/${orgId}/memory-groups/${group.id}`}
                    className="af-hover-bg inline-flex items-center gap-1 rounded-md px-2 py-1 text-[0.8125rem] whitespace-nowrap"
                    style={{ color: "var(--ink-3)" }}
                  >
                    <Brain size={14} aria-hidden /> View memory
                  </Link>
                )}

                {canManage &&
                  (isRenaming ? (
                    <>
                      <button className="af-btn" onClick={onRename} disabled={rename.isPending} aria-label="Save name">
                        <Check size={15} /> Save
                      </button>
                      <button className="af-btn" onClick={() => setRenaming(null)} aria-label="Cancel rename">
                        Cancel
                      </button>
                    </>
                  ) : (
                    <>
                      <button
                        className="af-hover-bg rounded-md p-1.5"
                        onClick={() => setRenaming({ id: group.id, name: group.name })}
                        aria-label={`Rename ${group.name}`}
                        style={{ color: "var(--ink-3)" }}
                      >
                        <Pencil size={15} />
                      </button>
                      <button
                        className="af-hover-bg rounded-md p-1.5"
                        onClick={() => setDeleting(group)}
                        aria-label={`Delete ${group.name}`}
                        style={{ color: "var(--danger, #dc2626)" }}
                      >
                        <Trash2 size={15} />
                      </button>
                    </>
                  ))}
              </div>

              {members.length > 0 && (
                <div className="mt-3 flex flex-wrap gap-1.5">
                  {members.map((agent) => (
                    <span
                      key={agent.id}
                      className="inline-flex items-center gap-1 rounded-full py-0.5 pr-1 pl-2.5 text-[0.8125rem]"
                      style={{ background: "var(--bg-elev)", color: "var(--ink-2)", border: "1px solid var(--line)" }}
                    >
                      {agent.name}
                      {canManage && (
                        <button
                          className="af-hover-bg rounded-full p-0.5"
                          aria-label={`Remove ${agent.name} from ${group.name}`}
                          onClick={async () => {
                            try {
                              await removeAgent.mutateAsync({ groupId: group.id, agentId: agent.id });
                            } catch (err) {
                              toastError(err, "Could not remove the agent.");
                            }
                          }}
                          style={{ color: "var(--ink-4)" }}
                        >
                          <X size={13} />
                        </button>
                      )}
                    </span>
                  ))}
                </div>
              )}

              {canManage && available.length > 0 && (
                <div className="mt-3">
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <button className="af-btn text-[0.8125rem]">
                        <Plus size={14} /> Add agent
                        <ChevronDownIcon size={13} className="opacity-50" />
                      </button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent className="max-h-72 overflow-y-auto">
                      {available.map((agent) => (
                        <DropdownMenuItem
                          key={agent.id}
                          onSelect={async () => {
                            try {
                              await addAgent.mutateAsync({ groupId: group.id, agentId: agent.id });
                            } catch (err) {
                              toastError(err, "Could not add the agent.");
                            }
                          }}
                        >
                          <span className="truncate">{agent.name}</span>
                          {agent.memoryGroupId && (
                            <span className="ml-2 text-[11px]" style={{ color: "var(--ink-4)" }}>
                              moves from another group
                            </span>
                          )}
                        </DropdownMenuItem>
                      ))}
                    </DropdownMenuContent>
                  </DropdownMenu>
                </div>
              )}
            </div>
          );
        })}
      </div>

      <ConfirmationDialog
        open={deleting !== null}
        onOpenChange={(open) => !open && setDeleting(null)}
        title={`Delete “${deleting?.name}”?`}
        description="This erases the group's shared memory for good and removes every agent from it. The agents themselves are not affected. This can't be undone."
        confirmLabel="Delete group"
        pendingLabel="Deleting…"
        variant="destructive"
        isPending={remove.isPending}
        onConfirm={onDelete}
      />
    </div>
  );
}
