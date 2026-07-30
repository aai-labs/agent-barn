"use client";

import { useEffect, useRef, useState, type CSSProperties } from "react";
import {
  Crown,
  Loader2,
  MoreHorizontal,
  PlusIcon,
  Send,
  Shield,
  Trash2,
  UserRound,
} from "lucide-react";
import { toast } from "sonner";

import { useCurrentUser } from "@/auth/providers/user-context-provider";
import { AppErrorState } from "@/components/app-error-state";
import { SearchInput } from "@/components/search-input";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

import { useMemberActions } from "../hooks/use-member-actions";
import { useOrganizationMembers } from "../hooks/use-organization-members";
import type { OrganizationMember, OrganizationRole } from "../schemas";
import { AddMemberDialog } from "./add-member-dialog";
import { InviteLinkField } from "./invite-link-field";

function initialsOf(member: OrganizationMember) {
  return (member.fullName ?? member.email)
    .split(" ")
    .map((w) => w[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
}

const ROLE_LABEL: Record<OrganizationRole, string> = {
  OWNER: "Owner",
  ADMIN: "Admin",
  MEMBER: "Member",
};

const ROLE_STYLE: Record<OrganizationRole, CSSProperties> = {
  OWNER: { background: "var(--accent-soft)", color: "var(--accent-ink)" },
  ADMIN: { background: "var(--bg-sunken)", color: "var(--ink-2)" },
  MEMBER: { background: "var(--bg-soft)", color: "var(--ink-3)" },
};

function RoleBadge({ role }: { role: OrganizationRole }) {
  return (
    <span
      className="flex-shrink-0 rounded-full px-2.5 py-1 text-[12px] font-medium"
      style={{ ...ROLE_STYLE[role], border: "1px solid var(--line)" }}
    >
      {ROLE_LABEL[role]}
    </span>
  );
}

const MENU_ITEM =
  "af-hover-bg w-full text-left flex items-center gap-2.5 px-3.5 py-2 text-[13.5px]";

function MemberActionsMenu({
  member,
  canManageOwnership,
  canRemove,
  onMakeAdmin,
  onMakeMember,
  onResend,
  onTransfer,
  onRemove,
}: {
  member: OrganizationMember;
  canManageOwnership: boolean;
  canRemove: boolean;
  onMakeAdmin: () => void;
  onMakeMember: () => void;
  onResend: () => void;
  onTransfer: () => void;
  onRemove: () => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function onDoc(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  const run = (fn: () => void) => {
    setOpen(false);
    fn();
  };

  return (
    <div ref={ref} className="relative flex-shrink-0">
      <button
        className="af-btn af-btn-icon"
        aria-label="Member actions"
        onClick={() => setOpen((v) => !v)}
      >
        <MoreHorizontal width={16} height={16} />
      </button>
      {open && (
        <div
          className="absolute right-0 top-[calc(100%+6px)] z-50 w-52 rounded-xl py-1"
          style={{
            background: "var(--bg-elev)",
            border: "1px solid var(--line)",
            boxShadow: "var(--shadow-pop)",
          }}
        >
          {canManageOwnership && member.role !== "ADMIN" && (
            <button className={MENU_ITEM} style={{ color: "var(--ink-2)" }} onClick={() => run(onMakeAdmin)}>
              <Shield width={15} height={15} style={{ color: "var(--ink-4)" }} /> Make admin
            </button>
          )}
          {member.role !== "MEMBER" &&
            (member.role !== "ADMIN" || canManageOwnership) && (
            <button className={MENU_ITEM} style={{ color: "var(--ink-2)" }} onClick={() => run(onMakeMember)}>
              <UserRound width={15} height={15} style={{ color: "var(--ink-4)" }} /> Make member
            </button>
          )}
          {member.isPending && (
            <button className={MENU_ITEM} style={{ color: "var(--ink-2)" }} onClick={() => run(onResend)}>
              <Send width={15} height={15} style={{ color: "var(--ink-4)" }} /> Resend invite
            </button>
          )}
          {canManageOwnership && (
            <button className={MENU_ITEM} style={{ color: "var(--ink-2)" }} onClick={() => run(onTransfer)}>
              <Crown width={15} height={15} style={{ color: "var(--ink-4)" }} /> Make owner
            </button>
          )}
          {canRemove && (
            <>
              <div style={{ borderTop: "1px solid var(--line)", margin: "4px 0" }} />
              <button className={MENU_ITEM} style={{ color: "var(--err)" }} onClick={() => run(onRemove)}>
                <Trash2 width={15} height={15} /> Remove from org
              </button>
            </>
          )}
        </div>
      )}
    </div>
  );
}

type ConfirmState = {
  title: string;
  description: string;
  actionLabel: string;
  destructive?: boolean;
  onConfirm: () => void;
};

export function MembersSection({
  organizationId,
  organizationName,
}: {
  organizationId: string;
  organizationName?: string;
}) {
  const { user, userContext } = useCurrentUser();
  const { members, isLoading, error, refetch } =
    useOrganizationMembers(organizationId);
  const { changeRole, removeMember, transferOwnership, resendInvite } =
    useMemberActions(organizationId);

  const [addOpen, setAddOpen] = useState(false);
  const [confirm, setConfirm] = useState<ConfirmState | null>(null);
  const [resendLink, setResendLink] = useState<string | null>(null);
  const [search, setSearch] = useState("");

  const term = search.trim().toLowerCase();
  const filteredMembers = term
    ? members.filter(
        (m) =>
          m.email.toLowerCase().includes(term) ||
          (m.fullName ?? "").toLowerCase().includes(term),
      )
    : members;

  const currentRole = userContext.organizationUsers?.find(
    (m) => m.organizationId === organizationId,
  )?.role;
  const canManageOwnership = user.isPlatformAdmin || currentRole === "OWNER";

  const onChangeRole = (member: OrganizationMember, role: OrganizationRole) => {
    changeRole.mutate(
      { userId: member.userId, role },
      {
        onSuccess: () => {
          toast.success(`${member.email} is now ${role.toLowerCase()}.`);
          setConfirm(null);
        },
        onError: (e) => toast.error(e.message || "Failed to change role"),
      },
    );
  };

  const confirmRoleChange = (
    member: OrganizationMember,
    role: OrganizationRole,
  ) =>
    setConfirm({
      title: role === "ADMIN" ? "Make admin" : "Make member",
      description:
        role === "ADMIN"
          ? `Make ${member.email} an admin? They'll be able to manage this organization's members.`
          : `Change ${member.email} to a member? They'll lose access to manage this organization's members.`,
      actionLabel: role === "ADMIN" ? "Make admin" : "Make member",
      onConfirm: () => onChangeRole(member, role),
    });

  const onResend = (member: OrganizationMember) => {
    resendInvite.mutate(member.userId, {
      onSuccess: (result) => {
        setResendLink(result.inviteLink);
        toast.success("Invite resent.");
      },
      onError: (e) => toast.error(e.message || "Failed to resend invite"),
    });
  };

  const confirmRemove = (member: OrganizationMember) =>
    setConfirm({
      title: "Remove member",
      description: `Remove ${member.email} from ${organizationName ?? "this organization"}?`,
      actionLabel: "Remove",
      destructive: true,
      onConfirm: () =>
        removeMember.mutate(member.userId, {
          onSuccess: () => {
            toast.success("Member removed.");
            setConfirm(null);
          },
          onError: (e) => toast.error(e.message || "Failed to remove member"),
        }),
    });

  const confirmTransfer = (member: OrganizationMember) =>
    setConfirm({
      title: "Transfer ownership",
      description: `Make ${member.email} the owner? You'll become an admin of this organization.`,
      actionLabel: "Transfer ownership",
      onConfirm: () =>
        transferOwnership.mutate(member.userId, {
          onSuccess: () => {
            toast.success("Ownership transferred.");
            setConfirm(null);
          },
          onError: (e) => toast.error(e.message || "Failed to transfer ownership"),
        }),
    });

  return (
    <section>
      <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between mb-4">
        <div>
          <h2 className="text-[16px] font-semibold m-0" style={{ color: "var(--ink)" }}>
            Members
          </h2>
          <p className="text-[13px] m-0 mt-0.5" style={{ color: "var(--ink-4)" }}>
            {members.length} {members.length === 1 ? "member" : "members"}
          </p>
        </div>
        <div className="flex items-center gap-2.5 w-full md:w-auto">
          <SearchInput
            onSearch={setSearch}
            placeholder="Search by name or email"
            ariaLabel="Search members"
            className="flex-1 md:w-64 md:flex-none"
          />
          <button
            className="af-btn af-btn-primary flex-shrink-0"
            onClick={() => setAddOpen(true)}
          >
            <PlusIcon width={15} height={15} /> Add member
          </button>
        </div>
      </div>

      <AddMemberDialog
        organizationId={organizationId}
        open={addOpen}
        onOpenChange={setAddOpen}
      />

      {isLoading ? (
        <div className="flex items-center gap-2 py-10 text-[13.5px]" style={{ color: "var(--ink-3)" }}>
          <Loader2 width={15} height={15} className="animate-spin" /> Loading members…
        </div>
      ) : error ? (
        <AppErrorState
          error={error}
          title="We couldn't load members"
          description="The members list is unavailable right now."
          onRetry={() => void refetch()}
          retryLabel="Retry members"
          className="min-h-[240px] p-0"
        />
      ) : (
        <div className="flex flex-col gap-2.5">
          {filteredMembers.map((member) => {
            const isOwner = member.role === "OWNER";
            const canRemoveMember =
              member.role !== "ADMIN" ||
              canManageOwnership ||
              member.userId === user.id;
            const hasMemberActions =
              canManageOwnership ||
              member.role !== "ADMIN" ||
              member.isPending ||
              canRemoveMember;
            return (
              <div
                key={member.userId}
                className="af-card flex items-center gap-4 px-5 py-3.5"
              >
                <div
                  className="w-9 h-9 rounded-full grid place-items-center text-[12px] font-semibold text-white flex-shrink-0"
                  style={{ background: "linear-gradient(135deg, #4338ca, #7c3aed)" }}
                >
                  {initialsOf(member)}
                </div>

                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="font-medium text-[14px] truncate" style={{ color: "var(--ink)" }}>
                      {member.fullName || member.email}
                    </span>
                    {member.isPending && !isOwner && (
                      <span
                        className="text-[11px] px-1.5 py-0.5 rounded-md font-medium"
                        style={{ background: "var(--warn-soft)", color: "var(--warn)" }}
                      >
                        Pending
                      </span>
                    )}
                  </div>
                  <div className="text-[12.5px] truncate" style={{ color: "var(--ink-3)" }}>
                    {member.email}
                  </div>
                </div>

                <RoleBadge role={member.role} />

                {!isOwner && hasMemberActions && (
                  <MemberActionsMenu
                    member={member}
                    canManageOwnership={canManageOwnership}
                    canRemove={canRemoveMember}
                    onMakeAdmin={() => confirmRoleChange(member, "ADMIN")}
                    onMakeMember={() => confirmRoleChange(member, "MEMBER")}
                    onResend={() => onResend(member)}
                    onTransfer={() => confirmTransfer(member)}
                    onRemove={() => confirmRemove(member)}
                  />
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* Confirm (remove / transfer) */}
      <Dialog open={!!confirm} onOpenChange={(v) => !v && setConfirm(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{confirm?.title}</DialogTitle>
            <DialogDescription>{confirm?.description}</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <button className="af-btn" onClick={() => setConfirm(null)}>
              Cancel
            </button>
            <button
              className="af-btn af-btn-primary"
              style={
                confirm?.destructive
                  ? { background: "var(--err)", borderColor: "var(--err)" }
                  : undefined
              }
              disabled={
                removeMember.isPending ||
                transferOwnership.isPending ||
                changeRole.isPending
              }
              onClick={() => confirm?.onConfirm()}
            >
              {confirm?.actionLabel}
            </button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Resend invite link */}
      <Dialog open={!!resendLink} onOpenChange={(v) => !v && setResendLink(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Invite resent</DialogTitle>
            <DialogDescription>
              A fresh invite email was sent. You can also share the link directly.
            </DialogDescription>
          </DialogHeader>
          {resendLink && <InviteLinkField link={resendLink} label="Invite link" />}
          <DialogFooter>
            <button className="af-btn af-btn-primary" onClick={() => setResendLink(null)}>
              Done
            </button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </section>
  );
}
