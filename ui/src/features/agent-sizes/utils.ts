import { formatBytes } from "@/features/resource-usage/format";

export const agentSizesKey = {
  /** Platform data: no Organization's cache is its. */
  platform: ["platform", "agent-sizes"] as const,
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
