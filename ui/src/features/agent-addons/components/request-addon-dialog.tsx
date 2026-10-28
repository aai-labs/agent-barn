"use client";

import { useState } from "react";
import { Loader2 } from "lucide-react";
import { toast } from "sonner";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";

import { useRequestAgentAddon } from "../hooks/use-agent-addons";
import type { AgentAddonKind, AgentAddonRequest } from "../schemas";
import { ADDON_KIND_LABELS } from "../utils";

type Field = { key: string; label: string; placeholder: string; hint?: string; multiline?: boolean };

// Each kind asks for exactly its pin; the API checks the same rules and answers in place.
const FIELDS: Record<AgentAddonKind, Field[]> = {
  pip: [
    { key: "name", label: "Package", placeholder: "humanize", hint: "Its name on PyPI." },
    { key: "version", label: "Version", placeholder: "4.12.3", hint: "One exact version." },
  ],
  npm: [
    { key: "name", label: "Package", placeholder: "left-pad", hint: "Its name on npm." },
    { key: "version", label: "Version", placeholder: "1.3.0", hint: "One exact version." },
  ],
  git: [
    { key: "name", label: "Name", placeholder: "toolkit", hint: "The folder it is checked out into." },
    { key: "url", label: "Repository URL", placeholder: "https://github.com/org/repo.git" },
    { key: "commit", label: "Commit", placeholder: "40-character commit SHA" },
  ],
  binary: [
    { key: "name", label: "Name", placeholder: "drawtool", hint: "The command the agent runs." },
    { key: "url", label: "Download URL", placeholder: "https://example.com/drawtool" },
    { key: "sha256", label: "SHA-256", placeholder: "64 hexadecimal characters" },
  ],
  command: [
    { key: "name", label: "Name", placeholder: "fonts" },
    {
      key: "command",
      label: "Command",
      placeholder: "curl -fsSL https://example.com/install.sh | bash",
      hint: "Run exactly as written with bash, without network credentials. Pin what it installs.",
      multiline: true,
    },
  ],
};

/**
 * Ask a Platform Administrator to approve an add-on for this Agent.
 *
 * Offers only the kinds the Agent's runtime can install. The request is reviewed exactly as
 * written and cannot be edited afterwards; an approved add-on is installed the next time the
 * Agent starts.
 */
export function RequestAddonDialog({
  agentId,
  agentName,
  availableKinds,
  open,
  onOpenChange,
}: {
  agentId: string;
  agentName: string;
  availableKinds: AgentAddonKind[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const requestAddon = useRequestAgentAddon(agentId);
  const [kind, setKind] = useState<AgentAddonKind>(availableKinds[0] ?? "pip");
  const [values, setValues] = useState<Record<string, string>>({});
  const [reason, setReason] = useState("");
  const fields = FIELDS[kind];
  const complete = fields.every((field) => (values[field.key] ?? "").trim()) && reason.trim();
  const failure = requestAddon.error instanceof Error ? requestAddon.error.message : null;

  const submit = () => {
    const value = (key: string) => (key === "command" ? (values[key] ?? "") : (values[key] ?? "").trim());
    const request = {
      kind,
      reason: reason.trim(),
      ...Object.fromEntries(fields.map((field) => [field.key, value(field.key)])),
    } as AgentAddonRequest;
    requestAddon.mutate(request, {
      onSuccess: (addon) => {
        toast.success(`Requested ${addon.name}. A platform administrator will review it.`);
        onOpenChange(false);
      },
    });
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[34rem]" data-testid="request-addon-dialog">
        <DialogHeader>
          <DialogTitle>Request an add-on for {agentName}</DialogTitle>
          <DialogDescription>
            A platform administrator reviews exactly what you enter here. Once approved, it is installed the next
            time the agent starts.
          </DialogDescription>
        </DialogHeader>

        <form
          className="flex flex-col gap-4"
          onSubmit={(event) => {
            event.preventDefault();
            submit();
          }}
        >
          <div className="flex flex-col gap-1.5">
            <label className="text-[0.8rem] font-medium" style={{ color: "var(--ink-2)" }} htmlFor="addon-kind">
              Kind
            </label>
            <Select
              value={kind}
              onValueChange={(next) => {
                setKind(next as AgentAddonKind);
                setValues({});
                requestAddon.reset();
              }}
              disabled={requestAddon.isPending}
            >
              <SelectTrigger id="addon-kind" aria-label="Kind" className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  {availableKinds.map((option) => (
                    <SelectItem key={option} value={option}>
                      {ADDON_KIND_LABELS[option]}
                    </SelectItem>
                  ))}
                </SelectGroup>
              </SelectContent>
            </Select>
          </div>

          {fields.map((field) => (
            <div key={`${kind}-${field.key}`} className="flex flex-col gap-1.5">
              <label
                className="text-[0.8rem] font-medium"
                style={{ color: "var(--ink-2)" }}
                htmlFor={`addon-${field.key}`}
              >
                {field.label}
              </label>
              {field.multiline ? (
                <Textarea
                  id={`addon-${field.key}`}
                  className="min-h-24 font-mono text-[0.8rem]"
                  placeholder={field.placeholder}
                  value={values[field.key] ?? ""}
                  disabled={requestAddon.isPending}
                  onChange={(event) => setValues((current) => ({ ...current, [field.key]: event.target.value }))}
                />
              ) : (
                <Input
                  id={`addon-${field.key}`}
                  placeholder={field.placeholder}
                  value={values[field.key] ?? ""}
                  disabled={requestAddon.isPending}
                  onChange={(event) => setValues((current) => ({ ...current, [field.key]: event.target.value }))}
                />
              )}
              {field.hint && (
                <span className="text-[0.72rem]" style={{ color: "var(--ink-4)" }}>
                  {field.hint}
                </span>
              )}
            </div>
          ))}

          <div className="flex flex-col gap-1.5">
            <label className="text-[0.8rem] font-medium" style={{ color: "var(--ink-2)" }} htmlFor="addon-reason">
              Why does the agent need it?
            </label>
            <Textarea
              id="addon-reason"
              className="min-h-20"
              placeholder="What the agent will use it for. The reviewer and the agent both read this."
              value={reason}
              maxLength={1000}
              disabled={requestAddon.isPending}
              onChange={(event) => setReason(event.target.value)}
            />
          </div>

          {failure && (
            <p className="m-0 text-[0.8rem]" style={{ color: "var(--err)" }} role="alert">
              {failure}
            </p>
          )}

          <DialogFooter className="gap-2">
            <button type="button" className="af-btn" onClick={() => onOpenChange(false)}>
              Cancel
            </button>
            <button type="submit" className="af-btn af-btn-primary" disabled={!complete || requestAddon.isPending}>
              {requestAddon.isPending && <Loader2 size={14} className="animate-spin" />} Request add-on
            </button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
