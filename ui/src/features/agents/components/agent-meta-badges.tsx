import { OpenClawIcon, HermesIcon, platformIcon } from "@/components/brand-icons";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import type { Agent } from "../schemas";

type Variant = "icon" | "full";

const TYPE_META = {
  hermes: {
    label: "Hermes",
    Icon: HermesIcon,
    tooltip: "Hermes",
  },
  openclaw: {
    label: "OpenClaw",
    Icon: OpenClawIcon,
    tooltip: "OpenClaw",
  },
} as const;

type BadgeIcon = (p: { size?: number; className?: string }) => React.ReactNode;

function Badge({
  Icon,
  label,
  tooltip,
  variant,
}: {
  Icon: BadgeIcon;
  label: string;
  tooltip: string;
  variant: Variant;
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span
          className="inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[0.75rem]"
          style={{
            background: "var(--bg-soft)",
            border: "1px solid var(--line)",
            color: "var(--ink-3)",
          }}
        >
          <Icon size={13} />
          {variant === "full" && <span>{label}</span>}
        </span>
      </TooltipTrigger>
      <TooltipContent>{tooltip}</TooltipContent>
    </Tooltip>
  );
}

export function AgentMetaBadges({
  agent,
  variant = "icon",
  className,
}: {
  agent: Pick<Agent, "agentType" | "configuredPlatformKeys">;
  variant?: Variant;
  className?: string;
}) {
  const type = TYPE_META[agent.agentType];

  return (
    <div className={`flex items-center gap-1.5 ${className ?? ""}`}>
      <Badge
        Icon={type.Icon}
        label={type.label}
        tooltip={type.tooltip}
        variant={variant}
      />
      {agent.configuredPlatformKeys.map((platformKey) => {
        const icon = platformIcon(platformKey, { size: 13 });
        if (!icon) return null;
        const label = platformKey.charAt(0).toUpperCase() + platformKey.slice(1);
        return (
          <Tooltip key={platformKey}>
            <TooltipTrigger asChild>
              <span
                className="inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[0.75rem]"
                style={{ background: "var(--bg-soft)", border: "1px solid var(--line)", color: "var(--ink-3)" }}
              >
                {icon}
                {variant === "full" && <span>{label}</span>}
              </span>
            </TooltipTrigger>
            <TooltipContent>{label}</TooltipContent>
          </Tooltip>
        );
      })}
    </div>
  );
}
