import { Badge } from "@/components/badge";

export function SkillSourceBadge({ source }: { source: string }) {
  return <Badge>{source === "aai_cli" ? "Built in" : "Custom"}</Badge>;
}
