import { createQueryKeyStructure } from "@/shared/query-keys";

export const AGENTS_PAGE_SIZE = 50;
export const TOOL_CALLS_PAGE_SIZE = 20;
const _agentsKeyBase = createQueryKeyStructure("agents");

export const agentsKey = {
  ..._agentsKeyBase,
  health: (id: string) => [..._agentsKeyBase.detail(id), "health"] as const,
};

export const toolCallsKey = createQueryKeyStructure("tool-calls");

const AGENT_COLORS = [
  ["#4f46e5", "#7c3aed"],
  ["#0d9488", "#15803d"],
  ["#b45309", "#c2410c"],
  ["#be185d", "#9d174d"],
  ["#0e6fd4", "#0369a1"],
  ["#7c2d12", "#9a3412"],
  ["#4338ca", "#5b21b6"],
  ["#0f766e", "#0e7490"],
];

export function agentColor(id: string): string {
  const seed = parseInt(id.replace(/-/g, "")[0], 16);
  const c = AGENT_COLORS[seed % AGENT_COLORS.length];
  return `linear-gradient(135deg, ${c[0]} 0%, ${c[1]} 100%)`;
}

export function agentInitials(name: string): string {
  return name.slice(0, 2).toUpperCase();
}
