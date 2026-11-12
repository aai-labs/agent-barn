import { Badge, type BadgeVariant } from "@/components/badge";

import type { AgentTaskStatus } from "../schemas";
import { TASK_STATUS_LABEL } from "../utils";

const STATUS_VARIANT: Record<AgentTaskStatus, BadgeVariant> = {
  open: "neutral",
  in_progress: "accent",
  done: "ok",
  failed: "danger",
};

export function TaskStatusBadge({ status }: { status: AgentTaskStatus }) {
  return <Badge variant={STATUS_VARIANT[status]}>{TASK_STATUS_LABEL[status]}</Badge>;
}
