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
import type { OrganizationMember } from "@/features/organizations/schemas";

import { useAgentShareRoles } from "../hooks/use-agent-share-roles";
import { useAgentShareSettings } from "../hooks/use-agent-share-settings";
import { defaultRoleId } from "../permissions";
import { ShareAddMember } from "./share-add-member";
import { ShareMemberRow } from "./share-member-row";
import { ShareRoleHelp } from "./share-role-help";
import { formatRoleName, ShareRoleSelect } from "./share-role-select";

interface ShareDialogProps {
  agentId: string;
  agentName: string;
  organizationId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

type DraftRow = {
  userId: string;
  email: string;
  fullName: string | null;
  isCreator: boolean;
  roleId: string;
};

type DraftGeneralAccess = { all: boolean; roleId: string | null };

export function ShareDialog({
  agentId,
  agentName,
  organizationId,
  open,
  onOpenChange,
}: ShareDialogProps) {
  const {
    roles,
    isLoading: rolesLoading,
    error: rolesError,
    refetch: refetchRoles,
  } = useAgentShareRoles(open);
  const {
    settings,
    isLoading: settingsLoading,
    error: settingsError,
    refetch: refetchSettings,
    save,
  } = useAgentShareSettings(agentId, open);

  const isLoading = rolesLoading || settingsLoading;
  const loadError = rolesError || settingsError;

  const [rows, setRows] = useState<DraftRow[]>([]);
  const [draftGeneral, setDraftGeneral] = useState<DraftGeneralAccess>({
    all: false,
    roleId: null,
  });
  const initializedRef = useRef(false);

  useEffect(() => {
    if (!open) {
      initializedRef.current = false;
      return;
    }
    if (initializedRef.current || isLoading || loadError || !settings) return;
    setRows(
      settings.assignments.map((a) => ({
        userId: a.userId,
        email: a.email,
        fullName: a.fullName,
        isCreator: a.isCreator,
        roleId: a.accessRole.id,
      })),
    );
    setDraftGeneral({
      all: !!settings.generalAccess.role,
      roleId: settings.generalAccess.role?.id ?? null,
    });
    initializedRef.current = true;
  }, [open, isLoading, loadError, settings]);

  const isDirty =
    !!settings &&
    (draftGeneral.all !== !!settings.generalAccess.role ||
      (draftGeneral.all && draftGeneral.roleId !== (settings.generalAccess.role?.id ?? null)) ||
      rows.length !== settings.assignments.length ||
      rows.some((row) => {
        const original = settings.assignments.find((a) => a.userId === row.userId);
        return !original || original.accessRole.id !== row.roleId;
      }));

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

  function onGrant(member: OrganizationMember, roleId: string) {
    setRows((prev) => [
      ...prev,
      {
        userId: member.userId,
        email: member.email,
        fullName: member.fullName ?? null,
        isCreator: false,
        roleId,
      },
    ]);
  }

  function onChangeRole(userId: string, roleId: string) {
    setRows((prev) => prev.map((r) => (r.userId === userId ? { ...r, roleId } : r)));
  }

  function onRemoveRow(userId: string) {
    setRows((prev) => prev.filter((r) => r.userId !== userId));
    // Tied to the specific removal (a toast), not a persistent section banner — a
    // static banner has nothing to anchor to once every direct grant is removed.
    if (draftGeneral.all && draftGeneral.roleId) {
      const generalRoleName = formatRoleName(
        roles.find((r) => r.id === draftGeneral.roleId)?.name ?? "",
      );
      toast.info(
        `Removed direct access. This Member still has ${generalRoleName} access via General access.`,
      );
    }
  }

  function onCancel() {
    onOpenChange(false);
  }

  async function onSave() {
    try {
      await save.mutateAsync({
        generalAccessRoleId: draftGeneral.all ? draftGeneral.roleId : null,
        assignments: rows.map((r) => ({ userId: r.userId, accessRoleId: r.roleId })),
      });
      toast.success("Sharing updated.");
      onOpenChange(false);
    } catch (e) {
      // Draft stays exactly as the user left it — the PUT is atomic server-side, so a
      // failure means nothing was applied; there is no partial state to reconcile.
      toast.error(e instanceof Error ? e.message : "Couldn't save sharing changes");
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next && save.isPending) return;
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
              void refetchSettings();
            }}
            retryLabel="Retry"
            className="min-h-[200px] p-0"
          />
        ) : (
          <>
            <div className="flex flex-col gap-5">
              <ShareAddMember
                organizationId={organizationId}
                roles={roles}
                onGrant={onGrant}
                disabled={save.isPending}
                isOpen={open}
                assignedUserIds={rows.map((r) => r.userId)}
              />

              <section>
                <h3 className="text-[13.5px] font-semibold mb-1" style={{ color: "var(--ink)" }}>
                  People with access
                </h3>
                <p className="text-[12px] mb-2" style={{ color: "var(--ink-4)" }}>
                  Organization Owners and Admins always have full access to every Agent
                  and aren&apos;t listed here.
                </p>
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
                        onRemove={() => onRemoveRow(row.userId)}
                        disabled={save.isPending}
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
                      disabled={save.isPending}
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
                      disabled={save.isPending}
                      ariaLabel="General access role"
                      className="w-32 flex-shrink-0"
                    />
                  )}
                </div>
              </section>
            </div>

            <DialogFooter>
              <button className="af-btn" onClick={onCancel} disabled={save.isPending}>
                Cancel
              </button>
              <button
                className="af-btn af-btn-primary"
                onClick={() => { void onSave(); }}
                disabled={save.isPending || !isDirty}
              >
                {save.isPending ? "Saving…" : "Save"}
              </button>
            </DialogFooter>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
