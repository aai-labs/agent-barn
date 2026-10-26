import { formatBytes } from "@/features/resource-usage/format";

export const agentSizesKey = {
  /** Platform data: no Organization's cache is its. */
  platform: ["platform", "agent-sizes"] as const,
  /** The catalog with one Organization's Agent counts; under `platform`, so catalog writes refresh it. */
  platformForOrganization: (organizationId: string) => ["platform", "agent-sizes", organizationId] as const,
  /** What one Organization may choose; keyed by it, so switching Organization never reuses another's. */
  organization: (organizationId: string) => ["organization-agent-sizes", organizationId] as const,
};

export const MIB = 1024 ** 2;

// The API's bounds, so the dialog refuses what the API would.
export const MAX_CPU_MILLICORES = 64_000;
export const MAX_MEMORY_BYTES = 256 * 1024 ** 3;

/** "0.05 vCPU", "2 vCPU": cores the way an administrator thinks of them. */
export function formatCpu(millicores: number): string {
  return `${Number((millicores / 1000).toFixed(3))} vCPU`;
}

export function formatMemory(bytes: number): string {
  return formatBytes(bytes);
}

/** "Large · 2 vCPU · 4 GiB": a size by what it may grow to, the way people compare them. */
export function describeSize(size: {
  name: string;
  cpuLimitMillicores: number;
  memoryLimitBytes: number;
}): string {
  return `${size.name} · ${formatCpu(size.cpuLimitMillicores)} · ${formatMemory(size.memoryLimitBytes)}`;
}

/** "1 agent", "3 agents". */
export function agentCountLabel(count: number): string {
  return `${count} ${count === 1 ? "agent" : "agents"}`;
}
