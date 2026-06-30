type ListKeyParams = {
  scope?: object;
  filters?: object;
};

export const createQueryKeyStructure = (baseKey: string) => ({
  all: [baseKey] as const,
  lists: () => [baseKey, "list"] as const,
  listScope: (scope: object) => [baseKey, "list", { ...scope }] as const,
  list: (params: ListKeyParams | object = {}) => {
    const { scope, filters, ...rest } = params as ListKeyParams & object;
    const resolvedScope = { ...(scope ?? {}), ...rest };
    const resolvedFilters = { ...(filters ?? {}) };
    return [baseKey, "list", resolvedScope, resolvedFilters] as const;
  },
  details: () => [baseKey, "detail"] as const,
  detail: (id: string) => [baseKey, id] as const,
});

export const slackConfigTokenKey = createQueryKeyStructure("slack-config-token");
