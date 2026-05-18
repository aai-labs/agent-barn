import type { Agent } from "../types";

interface AgentAvatarProps {
  agent: Pick<Agent, "color" | "initials" | "name">;
  size?: "xs" | "sm" | "md" | "lg" | "xl";
}

const sizeClasses = {
  xs: "w-[22px] h-[22px] text-[10.5px]",
  sm: "w-8 h-8 text-[12px]",
  md: "w-11 h-11 text-[14px]",
  lg: "w-14 h-14 text-[17px]",
  xl: "w-[72px] h-[72px] text-[22px]",
};

export function AgentAvatar({ agent, size = "md" }: AgentAvatarProps) {
  return (
    <div
      className={`${sizeClasses[size]} rounded-full grid place-items-center font-mono font-semibold text-white flex-shrink-0`}
      style={{ background: agent.color }}
    >
      {agent.initials}
    </div>
  );
}
