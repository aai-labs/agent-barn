"use client";

import { useCallback, useMemo, useState } from "react";
import { useAssistantDataUI, type DataMessagePartProps } from "@assistant-ui/react";

import type { WebChatApproval } from "../schemas";

export const APPROVAL_DATA_PART = "approval";

interface WebChatApprovalRendererProps {
  canAnswer: boolean;
  disabled: boolean;
  onAnswer: (choice: string, approvalId: string) => Promise<void>;
}

export function WebChatApprovalRenderer({ canAnswer, disabled, onAnswer }: WebChatApprovalRendererProps) {
  const [answered, setAnswered] = useState<ReadonlySet<string>>(() => new Set());

  const answer = useCallback(
    async (choice: string, approvalId: string) => {
      setAnswered((current) => new Set(current).add(approvalId));
      try {
        await onAnswer(choice, approvalId);
      } catch {
        setAnswered((current) => {
          const next = new Set(current);
          next.delete(approvalId);
          return next;
        });
      }
    },
    [onAnswer],
  );

  const dataUI = useMemo(() => {
    if (!canAnswer) return null;
    function ApprovalButtons({ data }: DataMessagePartProps<WebChatApproval>) {
      const isDisabled = disabled || answered.has(data.approvalId);
      return (
        <div className="mt-2 flex flex-wrap gap-2" role="group" aria-label="Command approval">
          {data.choices.map((choice: string) => (
            <button
              key={choice}
              type="button"
              className="af-btn af-btn-sm"
              disabled={isDisabled}
              onClick={() => void answer(choice, data.approvalId)}
            >
              {data.choiceLabels[choice] ?? choice}
            </button>
          ))}
        </div>
      );
    }
    return { name: APPROVAL_DATA_PART, render: ApprovalButtons };
  }, [canAnswer, disabled, answered, answer]);

  useAssistantDataUI(dataUI);

  return null;
}
