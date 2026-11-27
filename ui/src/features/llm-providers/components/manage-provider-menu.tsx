"use client";

import { useRef } from "react";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

import type { LlmProviderConnection } from "../schemas";
import { providerTitle } from "../utils";

export function ManageProviderMenu({
  connection,
  onModels,
  onOrganizations,
  onReplaceKey,
  onDelete,
}: {
  connection: LlmProviderConnection;
  /** Gets the Manage button, for the Models dialog to give focus back to when it closes. */
  onModels?: (trigger: HTMLElement | null) => void;
  /** Gets the Manage button, as `onModels` does. */
  onOrganizations: (trigger: HTMLElement | null) => void;
  /** Gets the Manage button, as `onModels` does. */
  onReplaceKey: (trigger: HTMLElement | null) => void;
  onDelete?: () => void;
}) {
  const trigger = useRef<HTMLButtonElement>(null);
  return (
    <DropdownMenu modal={false}>
      <DropdownMenuTrigger asChild>
        <button ref={trigger} type="button" className="af-btn" aria-label={`Manage ${providerTitle(connection)}`}>
          Manage
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start">
        {onModels && connection.hasApiKey && (
          <DropdownMenuItem onSelect={() => onModels(trigger.current)}>Models</DropdownMenuItem>
        )}
        <DropdownMenuItem onSelect={() => onOrganizations(trigger.current)}>Organizations</DropdownMenuItem>
        <DropdownMenuItem onSelect={() => onReplaceKey(trigger.current)}>
          {connection.hasApiKey ? "Replace key" : "Save a key"}
        </DropdownMenuItem>
        {onDelete && (
          <DropdownMenuItem variant="destructive" onSelect={onDelete}>
            Delete
          </DropdownMenuItem>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
