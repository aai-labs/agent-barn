"use client";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

import type { LlmProviderConnection } from "../schemas";

export function ManageProviderMenu({
  connection,
  onModels,
  onReplaceKey,
  onDelete,
}: {
  connection: LlmProviderConnection;
  onModels: () => void;
  onReplaceKey: () => void;
  onDelete: () => void;
}) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button type="button" className="af-btn">
          Manage
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start">
        {connection.hasApiKey && <DropdownMenuItem onSelect={onModels}>Models</DropdownMenuItem>}
        <DropdownMenuItem onSelect={onReplaceKey}>{connection.hasApiKey ? "Replace key" : "Save a key"}</DropdownMenuItem>
        <DropdownMenuItem variant="destructive" onSelect={onDelete}>
          Delete
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
