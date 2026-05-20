import type { Agent } from "../schemas";
import { agentColor, agentInitials } from "../utils";

interface AgentAvatarProps {
  agent: Pick<Agent, "id" | "name">;
  size?: "xs" | "sm" | "md" | "lg" | "xl";
}

const sizeClasses = {
  xs: "w-5.5 h-5.5 text-[0.656rem]",
  sm: "w-8 h-8 text-xs",
  md: "w-11 h-11 text-sm",
  lg: "w-14 h-14 text-[1.0625rem]",
  xl: "w-18 h-18 text-[1.375rem]",
};

export function AgentAvatar({ agent, size = "md" }: AgentAvatarProps) {
  return (
    <div
      className={`${sizeClasses[size]} rounded-full grid place-items-center font-mono font-semibold text-white flex-shrink-0`}
      style={{ background: agentColor(agent.id) }}
    >
      {agentInitials(agent.name)}
    </div>
  );
}
