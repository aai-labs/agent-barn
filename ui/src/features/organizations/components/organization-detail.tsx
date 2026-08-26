"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  CalendarDays,
  ChevronLeft,
  Loader2,
  Trash2,
  UserRound,
  Users,
} from "lucide-react";
import { toast } from "sonner";

import { useCurrentUser } from "@/auth/providers/user-context-provider";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

import { useDeleteOrganization } from "../hooks/use-organization-actions";
import { useOrganization } from "../hooks/use-organization";
import { useOrganizationMembers } from "../hooks/use-organization-members";
import { useRequireOrgManager } from "../hooks/use-require-org-manager";
import { MembersSection } from "./members-section";
import { DetailStatTile } from "@/components/detail-stat-tile";

import { organizationInitials } from "./organization-detail-utils";

export function OrganizationDetail({ organizationId }: { organizationId: string }) {
  // Member management is owner/admin-only; redirect a member here (e.g. via org switch).
  const canManage = useRequireOrgManager();
  const router = useRouter();
  const { user, userContext } = useCurrentUser();
  const { organization, isLoading } = useOrganization(organizationId);
  const { members, isLoading: membersLoading } =
    useOrganizationMembers(organizationId);
  const deleteOrganization = useDeleteOrganization();

  const [deleteOpen, setDeleteOpen] = useState(false);
  const [confirmName, setConfirmName] = useState("");

  const currentRole = userContext.organizationUsers?.find(
    (m) => m.organizationId === organizationId,
  )?.role;
  const canDelete = !!organization && (user.isPlatformAdmin || currentRole === "OWNER");

  const onDelete = () => {
    deleteOrganization.mutate(organizationId, {
      onSuccess: () => {
        toast.success("Organization deleted.");
        setDeleteOpen(false);
        router.push(user.isPlatformAdmin ? "/dashboard/platform/organizations" : "/");
      },
      onError: (e) => toast.error(e.message || "Failed to delete organization"),
    });
  };

  // Redirecting (member on an owner/admin page) — render nothing meanwhile.
  if (!canManage) {
    return null;
  }

  if (isLoading) {
    return (
      <div className="af-page">
        <div
          className="flex items-center gap-2 py-10 text-[13.5px]"
          style={{ color: "var(--ink-3)" }}
        >
          <Loader2 width={15} height={15} className="animate-spin" /> Loading
          organization…
        </div>
      </div>
    );
  }

  if (!organization) {
    return (
      <div className="af-page">
        <div className="text-[14px]" style={{ color: "var(--ink-3)" }}>
          Organization not found.
        </div>
      </div>
    );
  }

  const memberCount = membersLoading ? null : members.length;

  return (
    <div className="af-page">
      {user.isPlatformAdmin && (
        <Link
          href="/dashboard/platform/organizations"
          className="inline-flex items-center gap-1 text-[13px] mb-4"
          style={{ color: "var(--ink-3)" }}
        >
          <ChevronLeft width={14} height={14} /> Organizations
        </Link>
      )}

      {/* Header: monogram + name/description, quiet delete on the right */}
      <div className="flex items-start gap-4 mb-7">
        <div
          className="grid h-14 w-14 flex-shrink-0 place-items-center rounded-2xl text-[18px] font-semibold text-white"
          style={{ background: "linear-gradient(135deg, #4338ca, #7c3aed)" }}
          aria-hidden
        >
          {organizationInitials(organization.name)}
        </div>

        <div className="min-w-0 flex-1 pt-0.5">
          <div className="flex items-center gap-2">
            <h1
              className="m-0 truncate text-[26px] font-semibold tracking-tight"
              style={{ color: "var(--ink)" }}
            >
              {organization.name}
            </h1>
          </div>
          <p className="m-0 mt-1 text-[14px]" style={{ color: "var(--ink-3)" }}>
            {organization.description || "No description"}
          </p>
        </div>

        {canDelete && (
          <button
            className="af-btn flex-shrink-0"
            style={{ color: "var(--err)", borderColor: "var(--line)" }}
            onClick={() => {
              setConfirmName("");
              setDeleteOpen(true);
            }}
          >
            <Trash2 width={15} height={15} /> Delete organization
          </button>
        )}
      </div>

      {/* Stat row */}
      <div className="grid gap-3 sm:grid-cols-3 mb-9">
        <DetailStatTile icon={<Users width={14} height={14} />} label="Members">
          {memberCount === null
            ? "—"
            : `${memberCount} ${memberCount === 1 ? "member" : "members"}`}
        </DetailStatTile>
        <DetailStatTile icon={<UserRound width={14} height={14} />} label="Owner">
          <span title={organization.ownerEmail ?? undefined}>
            {organization.ownerName || organization.ownerEmail || "No owner"}
          </span>
        </DetailStatTile>
        <DetailStatTile icon={<CalendarDays width={14} height={14} />} label="Created">
          {new Date(organization.createdAt).toLocaleDateString(undefined, {
            year: "numeric",
            month: "short",
            day: "numeric",
          })}
        </DetailStatTile>
      </div>

      <div style={{ borderTop: "1px solid var(--line)" }} className="pt-8">
        <MembersSection
          organizationId={organizationId}
          organizationName={organization.name}
        />
      </div>

      <Dialog open={deleteOpen} onOpenChange={setDeleteOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete organization</DialogTitle>
            <DialogDescription>
              This permanently deletes <strong>{organization.name}</strong>{" "}
              and all its agents, templates, skills, and memberships. This
              can&apos;t be undone. Type the organization name to confirm.
            </DialogDescription>
          </DialogHeader>
          <input
            type="text"
            className="af-input w-full"
            value={confirmName}
            onChange={(e) => setConfirmName(e.target.value)}
            placeholder={organization.name}
            aria-label="Confirm organization name"
            autoComplete="off"
          />
          <DialogFooter>
            <button className="af-btn" onClick={() => setDeleteOpen(false)}>
              Cancel
            </button>
            <button
              className="af-btn af-btn-primary"
              style={{ background: "var(--err)", borderColor: "var(--err)" }}
              disabled={
                confirmName !== organization.name || deleteOrganization.isPending
              }
              onClick={onDelete}
            >
              {deleteOrganization.isPending ? "Deleting…" : "Delete organization"}
            </button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
