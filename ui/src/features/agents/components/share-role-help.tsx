"use client";

import { useState } from "react";
import { HelpCircle } from "lucide-react";

import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

import type { AgentAccessRoleRead } from "../schemas";
import { ShareRoleLegend } from "./share-role-legend";

export function ShareRoleHelp({ roles }: { roles: AgentAccessRoleRead[] }) {
  const [open, setOpen] = useState(false);

  return (
    <>
      <button
        type="button"
        className="af-btn af-btn-icon absolute top-3 right-12"
        aria-label="What can each Agent Access Role do?"
        onClick={() => setOpen(true)}
      >
        <HelpCircle width={15} height={15} />
      </button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>Agent Access Roles</DialogTitle>
          </DialogHeader>
          <ShareRoleLegend roles={roles} />
        </DialogContent>
      </Dialog>
    </>
  );
}
