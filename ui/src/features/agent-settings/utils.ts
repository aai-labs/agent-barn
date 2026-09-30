export const agentSettingsKey = {
  all: ["agent-settings"] as const,
  detail: (organizationId: string) => ["agent-settings", organizationId] as const,
};
