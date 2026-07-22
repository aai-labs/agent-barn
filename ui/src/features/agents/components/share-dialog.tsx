"use client";

import { useEffect, useRef, useState } from "react";
import { Loader2 } from "lucide-react";
import { toast } from "sonner";

import { AppErrorState } from "@/components/app-error-state";
import { LockIcon, UsersIcon } from "@/components/icons";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

import { useAgentAccess } from "../hooks/use-agent-access";
import { useAgentAccessMutations } from "../hooks/use-agent-access-mutations";
import { useAgentAccessRoles } from "../hooks/use-agent-access-roles";
import { useAgentGeneralAccess } from "../hooks/use-agent-general-access";
import type { AgentAccessCandidateRead } from "../schemas";
import { defaultRoleId } from "../permissions";
import { ShareAddMember } from "./share-add-member";
import { ShareMemberRow } from "./share-member-row";
import { ShareRoleHelp } from "./share-role-help";
import { formatRoleName, ShareRoleSelect } from "./share-role-select";

interface ShareDialogProps {
  agentId: string;
  agentName: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

type DraftRow = {
  userId: string;
  email: string;
  fullName: string | null;
  isCreator: boolean;
  roleId: string;
  isNew: boolean;
};

type DraftGeneralAccess = { all: boolean; roleId: string | null };

export function ShareDialog({
  agentId,
  agentName,
  open,
  onOpenChange,
}: ShareDialogProps) {
  const {
    roles,
    isLoading: rolesLoading,
    error: rolesError,
    refetch: refetchRoles,
  } = useAgentAccessRoles(open);
  const {
    members,
    isLoading: membersLoading,
    error: membersError,
    refetch: refetchMembers,
  } = useAgentAccess(agentId, open);
  const {
    generalAccess,
    isLoading: generalAccessLoading,
    error: generalAccessError,
    setGeneralAccess,
    removeGeneralAccess,
  } = useAgentGeneralAccess(agentId, open);
  const { grantAccess, changeAccessRole, revokeAccess } =
    useAgentAccessMutations(agentId);

  const isLoading = rolesLoading || membersLoading || generalAccessLoading;
  const loadError = rolesError || membersError || generalAccessError;

  const [rows, setRows] = useState<DraftRow[]>([]);
  const [removedUserIds, setRemovedUserIds] = useState<Set<string>>(new Set());
  const [draftGeneral, setDraftGeneral] = useState<DraftGeneralAccess>({
    all: false,
    roleId: null,
  });
  const [isSaving, setIsSaving] = useState(false);
  const initializedRef = useRef(false);

  useEffect(() => {
    if (!open) {
      initializedRef.current = false;
      return;
    }
    if (initializedRef.current || isLoading || loadError) return;
    setRows(
      members.map((m) => ({
        userId: m.userId,
        email: m.email,
        fullName: m.fullName,
        isCreator: m.isCreator,
        roleId: m.accessRole.id,
        isNew: false,
      })),
    );
    setRemovedUserIds(new Set());
    setDraftGeneral({ all: !!generalAccess?.role, roleId: generalAccess?.role?.id ?? null });
    initializedRef.current = true;
  }, [open, isLoading, loadError, members, generalAccess]);

  const isDirty =
    removedUserIds.size > 0 ||
    rows.some((row) => {
      if (row.isNew) return true;
      const original = members.find((m) => m.userId === row.userId);
      return original && original.accessRole.id !== row.roleId;
    }) ||
    draftGeneral.all !== !!generalAccess?.role ||
    (draftGeneral.all && draftGeneral.roleId !== (generalAccess?.role?.id ?? null));

  function onGeneralAccessModeChange(mode: "restricted" | "all") {
    setDraftGeneral(
      mode === "restricted"
        ? { all: false, roleId: null }
        : { all: true, roleId: draftGeneral.roleId ?? defaultRoleId(roles) ?? null },
    );
  }

  function onGeneralAccessRoleChange(roleId: string) {
    setDraftGeneral({ all: true, roleId });
  }

  function onGrant(candidate: AgentAccessCandidateRead, roleId: string) {
    // If this Member was staged for removal (not yet saved), re-adding them restores
    // the original grant rather than staging a brand-new one.
    const wasStagedForRemoval = removedUserIds.has(candidate.userId);
    if (wasStagedForRemoval) {
      setRemovedUserIds((prev) => {
        const next = new Set(prev);
        next.delete(candidate.userId);
        return next;
      });
    }
    setRows((prev) => [
      ...prev,
      {
        userId: candidate.userId,
        email: candidate.email,
        fullName: candidate.fullName,
        isCreator: candidate.isCreator,
        roleId,
        isNew: !wasStagedForRemoval && !members.some((m) => m.userId === candidate.userId),
      },
    ]);
  }

  function onChangeRole(userId: string, roleId: string) {
    setRows((prev) => prev.map((r) => (r.userId === userId ? { ...r, roleId } : r)));
  }

  function onRemoveRow(row: DraftRow) {
    setRows((prev) => prev.filter((r) => r.userId !== row.userId));
    if (!row.isNew) {
      setRemovedUserIds((prev) => new Set(prev).add(row.userId));
    }
  }

  function onCancel() {
    onOpenChange(false);
  }

  async function onSave() {
    const originalById = new Map(members.map((m) => [m.userId, m.accessRole.id]));
    const originalGeneralRoleId = generalAccess?.role?.id ?? null;
    const ops: Promise<unknown>[] = [];

    if (draftGeneral.all && draftGeneral.roleId && draftGeneral.roleId !== originalGeneralRoleId) {
      ops.push(setGeneralAccess.mutateAsync(draftGeneral.roleId));
    } else if (!draftGeneral.all && originalGeneralRoleId) {
      ops.push(removeGeneralAccess.mutateAsync());
    }

    for (const userId of removedUserIds) {
      ops.push(revokeAccess.mutateAsync(userId));
    }
    for (const row of rows) {
      if (row.isNew) {
        ops.push(grantAccess.mutateAsync({ userId: row.userId, accessRoleId: row.roleId }));
      } else if (originalById.get(row.userId) !== row.roleId) {
        ops.push(
          changeAccessRole.mutateAsync({ userId: row.userId, accessRoleId: row.roleId }),
        );
      }
    }

    if (ops.length === 0) {
      onOpenChange(false);
      return;
    }

    setIsSaving(true);
    const results = await Promise.allSettled(ops);
    setIsSaving(false);

    const failed = results.filter(
      (r): r is PromiseRejectedResult => r.status === "rejected",
    );
    if (failed.length === 0) {
      toast.success("Sharing updated.");
      onOpenChange(false);
    } else {
      const reason = failed[0].reason;
      toast.error(reason instanceof Error ? reason.message : "Some changes couldn't be saved");
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next && isSaving) return;
        onOpenChange(next);
      }}
    >
      <DialogContent className="max-w-xl max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Share {agentName}</DialogTitle>
          <DialogDescription>
            Manage who can access this Agent, directly or through General access.
          </DialogDescription>
        </DialogHeader>

        {!isLoading && !loadError && roles.length > 0 && <ShareRoleHelp roles={roles} />}

        {isLoading ? (
          <div
            className="flex items-center gap-2 py-10 text-[13.5px]"
            style={{ color: "var(--ink-3)" }}
          >
            <Loader2 width={15} height={15} className="animate-spin" /> Loading sharing
            settings…
          </div>
        ) : loadError ? (
          <AppErrorState
            error={loadError}
            title="We couldn't load sharing settings"
            description="This Agent may no longer be available."
            onRetry={() => {
              void refetchRoles();
              void refetchMembers();
            }}
            retryLabel="Retry"
            className="min-h-[200px] p-0"
          />
        ) : (
          <>
            <div className="flex flex-col gap-5">
              <ShareAddMember
                agentId={agentId}
                roles={roles}
                onGrant={onGrant}
                disabled={isSaving}
                isOpen={open}
                excludeUserIds={rows.map((r) => r.userId)}
                localCandidates={members.filter((m) => removedUserIds.has(m.userId))}
              />

              <section>
                <h3 className="text-[13.5px] font-semibold mb-1" style={{ color: "var(--ink)" }}>
                  People with access
                </h3>
                <p className="text-[12px] mb-2" style={{ color: "var(--ink-4)" }}>
                  Organization Owners and Admins always have full access to every Agent
                  and aren&apos;t listed here.
                </p>
                {draftGeneral.all && draftGeneral.roleId && (
                  <p className="text-[12px] mb-2" style={{ color: "var(--ink-4)" }}>
                    Removing a direct grant removes only that grant — Members still get{" "}
                    {formatRoleName(
                      roles.find((r) => r.id === draftGeneral.roleId)?.name ?? "",
                    )}{" "}
                    access via General access.
                  </p>
                )}
                {rows.length === 0 ? (
                  <p className="text-[13px] py-2" style={{ color: "var(--ink-4)" }}>
                    No direct access grants yet.
                  </p>
                ) : (
                  <div className="divide-y" style={{ borderColor: "var(--line)" }}>
                    {rows.map((row) => (
                      <ShareMemberRow
                        key={row.userId}
                        member={row}
                        roleId={row.roleId}
                        roles={roles}
                        onChangeRole={(roleId) => onChangeRole(row.userId, roleId)}
                        onRemove={() => onRemoveRow(row)}
                        disabled={isSaving}
                      />
                    ))}
                  </div>
                )}
              </section>

              <section>
                <h3 className="text-[13.5px] font-semibold mb-2" style={{ color: "var(--ink)" }}>
                  General access
                </h3>
                <div className="flex items-start gap-3">
                  <div
                    className="w-9 h-9 rounded-full grid place-items-center flex-shrink-0"
                    style={{ background: "var(--bg-soft)", color: "var(--ink-3)" }}
                  >
                    {draftGeneral.all ? <UsersIcon size={15} /> : <LockIcon size={15} />}
                  </div>
                  <div className="flex-1 min-w-0 pt-px">
                    <select
                      className="af-select"
                      aria-label="General access"
                      value={draftGeneral.all ? "all" : "restricted"}
                      disabled={isSaving}
                      onChange={(e) =>
                        onGeneralAccessModeChange(e.target.value as "restricted" | "all")
                      }
                    >
                      <option value="restricted">Restricted</option>
                      <option value="all">All Organization Members</option>
                    </select>
                    <p className="mt-1 text-[12px]" style={{ color: "var(--ink-4)" }}>
                      {draftGeneral.all
                        ? "Applies automatically to current and future accepted Members."
                        : "Only people granted direct access can open this Agent."}
                    </p>
                  </div>
                  {draftGeneral.all && draftGeneral.roleId && (
                    <ShareRoleSelect
                      roles={roles}
                      value={draftGeneral.roleId}
                      onChange={onGeneralAccessRoleChange}
                      disabled={isSaving}
                      ariaLabel="General access role"
                      className="w-32 flex-shrink-0"
                    />
                  )}
                </div>
              </section>
            </div>

            <DialogFooter>
              <button className="af-btn" onClick={onCancel} disabled={isSaving}>
                Cancel
              </button>
              <button
                className="af-btn af-btn-primary"
                onClick={() => { void onSave(); }}
                disabled={isSaving || !isDirty}
              >
                {isSaving ? "Saving…" : "Save"}
              </button>
            </DialogFooter>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
