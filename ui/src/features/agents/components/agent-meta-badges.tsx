import { SlackIcon, TeamsIcon, TelegramIcon } from "@/components/icons";
import { OpenClawIcon, HermesIcon } from "@/components/brand-icons";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import type { Agent } from "../schemas";

type Variant = "icon" | "full";

const PLATFORM_META = {
  slack: {
    label: "Slack",
    Icon: SlackIcon,
    tooltip: "Connected via Slack",
  },
  teams: {
    label: "Teams",
    Icon: TeamsIcon,
    tooltip: "Connected via Microsoft Teams",
  },
  telegram: {
    label: "Telegram",
    Icon: TelegramIcon,
    tooltip: "Connected via Telegram",
  },
} as const;

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
  agent: Pick<Agent, "platform" | "agentType">;
  variant?: Variant;
  className?: string;
}) {
  const platform = PLATFORM_META[agent.platform];
  const type = TYPE_META[agent.agentType];

  return (
    <div className={`flex items-center gap-1.5 ${className ?? ""}`}>
      <Badge
        Icon={type.Icon}
        label={type.label}
        tooltip={type.tooltip}
        variant={variant}
      />
      <Badge
        Icon={platform.Icon}
        label={platform.label}
        tooltip={platform.tooltip}
        variant={variant}
      />
    </div>
  );
}
