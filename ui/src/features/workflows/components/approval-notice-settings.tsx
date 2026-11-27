"use client";

import { Search } from "lucide-react";
import { useId, useState } from "react";

import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { DirectoryPickerDialog } from "@/features/communication-connections/components/directory-picker-dialog";
import {
  useCommunicationConnectionDirectory,
  useSlackWorkspaces,
} from "@/features/communication-connections/hooks/use-communication-connections";
import { getErrorDisplay } from "@/shared/api/error/get-error-display";

import { type ApprovalNotice } from "../schemas";

export const APPROVAL_NOTICE_ACCESS_NOTE =
  "This Slack user must have an Agent Barn account with permission to update the Agent (agent.update). Otherwise they can open the link but cannot decide.";

/** Turning approval requests on needs a chosen user; returns the message to show, if any. */
export function approvalNoticeProblem(notice: ApprovalNotice): string | null {
  return notice.enabled && !notice.slackUserId
    ? "Choose the Slack user who receives approval requests, or turn them off."
    : null;
}

/**
 * Send approval requests: when a step's command needs a decision, one chosen Slack user gets a
 * direct message linking to the run. The decision itself is made on the web.
 */
export function ApprovalNoticeSettings({
  value,
  onChange,
  revealed,
}: {
  value: ApprovalNotice;
  onChange: (value: ApprovalNotice) => void;
  /** After a save attempt, a missing user shows its message. */
  revealed: boolean;
}) {
  const id = useId();
  const workspaces = useSlackWorkspaces(value.enabled);
  const reachable = workspaces.data ?? [];
  const [chosenTeam, setChosenTeam] = useState<string>("");
  const [picking, setPicking] = useState(false);
  const teamId =
    chosenTeam ||
    value.slackTeamId ||
    (reachable.length === 1 ? reachable[0].teamId : "");
  const workspace = reachable.find((item) => item.teamId === teamId);
  const connection = workspace?.connections[0];
  const directory = useCommunicationConnectionDirectory(
    connection?.agentId ?? "",
    connection?.connectionId ?? "",
    "users",
    "",
    picking,
  );
  const problem = revealed ? approvalNoticeProblem(value) : null;
  const selectedName = value.slackUserName || value.slackUserId;

  return (
    <div data-section="approval-notice" className="space-y-3">
      <label className="flex items-center gap-2.5 text-sm font-semibold">
        <button
          type="button"
          role="switch"
          aria-checked={value.enabled}
          aria-label="Send approval requests"
          onClick={() => onChange({ ...value, enabled: !value.enabled })}
          className="relative h-5 w-9 shrink-0 rounded-full transition-colors disabled:cursor-not-allowed disabled:opacity-50"
          style={{ backgroundColor: value.enabled ? "var(--ink)" : "var(--line)" }}
        >
          <span
            className={`absolute top-0.5 left-0.5 h-4 w-4 rounded-full bg-white transition-transform ${value.enabled ? "translate-x-4" : ""}`}
          />
        </button>
        Send approval requests
      </label>
      <p className="-mt-1.5 text-xs text-[var(--ink-3)]">
        When a step’s command needs a decision, a direct message links one person to the run.
        They approve or decline there; the message never shows the command.
      </p>
      {value.enabled && (
        <div className="space-y-3 rounded-xl border border-[var(--line)] bg-[var(--bg-elev)] p-4">
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1.5">
              <p id={`${id}-platform`} className="text-xs font-semibold">
                Messaging platform
              </p>
              <Select value="slack" onValueChange={() => undefined}>
                <SelectTrigger aria-labelledby={`${id}-platform`}>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectGroup>
                    <SelectItem value="slack">Slack</SelectItem>
                  </SelectGroup>
                </SelectContent>
              </Select>
            </div>
            {reachable.length > 1 && (
              <div className="space-y-1.5">
                <p id={`${id}-workspace`} className="text-xs font-semibold">
                  Slack workspace
                </p>
                <Select
                  value={teamId}
                  onValueChange={(next) => {
                    setChosenTeam(next);
                    // A user belongs to one workspace; choosing another clears them.
                    if (next !== value.slackTeamId)
                      onChange({ ...value, slackUserId: null, slackUserName: null, slackTeamId: null });
                  }}
                >
                  <SelectTrigger aria-labelledby={`${id}-workspace`}>
                    <SelectValue placeholder="Choose a workspace" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectGroup>
                      {reachable.map((item) => (
                        <SelectItem key={item.teamId} value={item.teamId}>
                          {item.name}
                        </SelectItem>
                      ))}
                    </SelectGroup>
                  </SelectContent>
                </Select>
              </div>
            )}
          </div>
          <div className="space-y-1.5">
            <p id={`${id}-user`} className="text-xs font-semibold">
              Slack user
            </p>
            <div className="flex flex-wrap items-center gap-2">
              <span
                aria-labelledby={`${id}-user`}
                className="min-w-0 flex-1 truncate rounded-lg border border-[var(--line)] px-3 py-2 text-sm"
                style={{ color: selectedName ? "var(--ink)" : "var(--ink-4)" }}
              >
                {selectedName ?? "No one chosen"}
              </span>
              <button
                type="button"
                className="af-btn af-btn-sm"
                aria-label="Choose Slack user"
                disabled={!connection}
                onClick={() => setPicking(true)}
              >
                <Search size={13} aria-hidden /> Choose
              </button>
            </div>
            {workspaces.isLoading && (
              <p role="status" className="text-xs text-[var(--ink-3)]">
                Loading Slack workspaces…
              </p>
            )}
            {workspaces.error && (
              <p role="alert" className="text-xs text-[var(--err)]">
                {getErrorDisplay(workspaces.error).description}
              </p>
            )}
            {workspaces.data && reachable.length === 0 && (
              <p className="text-xs text-[var(--ink-3)]">
                None of the agents you can update has Slack connected. Connect Slack to an
                agent to choose someone here.
              </p>
            )}
            {reachable.length > 1 && !teamId && (
              <p className="text-xs text-[var(--ink-3)]">Choose the workspace first.</p>
            )}
            <p className="text-xs text-[var(--ink-3)]">{APPROVAL_NOTICE_ACCESS_NOTE}</p>
            {problem && (
              <p role="alert" className="text-xs text-[var(--err)]">
                {problem}
              </p>
            )}
          </div>
        </div>
      )}
      {connection && workspace && (
        <DirectoryPickerDialog
          open={picking}
          onOpenChange={setPicking}
          title="Choose who receives approval requests"
          description={`People in ${workspace.name}, searched through ${connection.agentName}'s Slack connection.`}
          searchPlaceholder="Search people…"
          entries={directory.data ?? []}
          selected={value.slackUserId ? [value.slackUserId] : []}
          isLoading={directory.isLoading}
          error={directory.error ? getErrorDisplay(directory.error).description : null}
          multiple={false}
          onConfirm={(ids) => {
            const entry = (directory.data ?? []).find((item) => item.id === ids[0]);
            if (!entry) return;
            onChange({
              ...value,
              slackUserId: entry.id,
              slackUserName: entry.label,
              slackTeamId: workspace.teamId,
            });
          }}
        />
      )}
    </div>
  );
}
