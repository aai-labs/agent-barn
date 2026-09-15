"use client";

import { useMemo } from "react";
import { useAssistantDataUI, type DataMessagePartProps } from "@assistant-ui/react";

import type { WebChatApproval } from "../schemas";

export const APPROVAL_DATA_PART = "approval";

const CHOICE_LABELS: Record<string, string> = {
  once: "Allow once",
  session: "Allow for session",
  always: "Always allow",
  deny: "Deny",
};

interface WebChatApprovalRendererProps {
  canAnswer: boolean;
  disabled: boolean;
  onAnswer: (choice: string, approvalId: string) => Promise<void>;
}

export function WebChatApprovalRenderer({ canAnswer, disabled, onAnswer }: WebChatApprovalRendererProps) {
  const dataUI = useMemo(() => {
    if (!canAnswer) return null;
    function ApprovalButtons({ data }: DataMessagePartProps<WebChatApproval>) {
      return (
        <div className="mt-2 flex flex-wrap gap-2" role="group" aria-label="Command approval">
          {data.choices.map((choice: string) => (
            <button
              key={choice}
              type="button"
              className="af-btn af-btn-sm"
              disabled={disabled}
              onClick={() => void onAnswer(choice, data.approvalId)}
            >
              {CHOICE_LABELS[choice] ?? choice}
            </button>
          ))}
        </div>
      );
    }
    return { name: APPROVAL_DATA_PART, render: ApprovalButtons };
  }, [canAnswer, disabled, onAnswer]);

  useAssistantDataUI(dataUI);
  return null;
}
