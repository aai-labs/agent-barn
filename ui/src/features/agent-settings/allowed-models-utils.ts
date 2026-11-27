const GATEWAY_PREFIX = "litellm/";
const OPENROUTER_ENTRY_PREFIX = "openrouter/";

export const stripPrefix = (model: string) => model.replace(/^litellm\/openrouter\//, "");

export const toEntry = (value: string) => value.replace(/^litellm\//, "");

const toValue = (entry: string) => `${GATEWAY_PREFIX}${entry}`;

export const entryLabel = (entry: string) =>
  entry.startsWith(OPENROUTER_ENTRY_PREFIX) ? entry.slice(OPENROUTER_ENTRY_PREFIX.length) : entry;

// Stored allowlists can hold OpenRouter glob patterns such as "openrouter/*" or
// "openrouter/openai/*". Detect them so they can be expanded against the live catalog
// rather than shown as bogus "not in catalog" orphans.
const isGlob = (model: string) => /[*?[\]]/.test(model);

const globToRegExp = (pattern: string) => {
  const escaped = pattern
    .replace(/[.+^${}()|\\]/g, "\\$&")
    .replace(/\*/g, ".*")
    .replace(/\?/g, ".");
  return new RegExp(`^${escaped}$`, "i");
};

// Catalog values whose allowlist entry matches a glob pattern.
const expandGlob = (pattern: string, catalog: { value: string }[]) => {
  const re = globToRegExp(toEntry(pattern).toLowerCase());
  return catalog.map((entry) => entry.value).filter((value) => re.test(toEntry(value).toLowerCase()));
};

export const getPrefixedModels = (stored: string[] | undefined, catalog: { value: string }[]) => {
  const catalogValues = new Set(catalog.map((entry) => entry.value));
  const resolved = new Set<string>();
  for (const model of stored || []) {
    if (catalogValues.has(model)) {
      resolved.add(model);
      continue;
    }
    const value = toValue(model);
    if (catalogValues.has(value)) {
      resolved.add(value);
      continue;
    }
    if (isGlob(model)) {
      for (const value of expandGlob(model, catalog)) resolved.add(value);
      continue;
    }
    // Unknown literal — getOrphanedModels preserves it separately.
  }
  return [...resolved];
};

// Stored entries that resolve to nothing in the current catalog: a literal the catalog
// no longer carries, or a glob matching nothing. Kept separate so a save preserves them
// instead of silently dropping a model OpenRouter has since removed.
export const getOrphanedModels = (stored: string[] | undefined, catalog: { value: string }[]) => {
  const catalogValues = new Set(catalog.map((entry) => entry.value));
  return (stored || []).filter((model) => {
    if (catalogValues.has(model) || catalogValues.has(toValue(model))) return false;
    if (isGlob(model)) return expandGlob(model, catalog).length === 0;
    return true;
  });
};

/**
 * The catalog-recognized baseline used for both the initial selection and the dirty
 * check: the organization's matched models plus its default model, which is always
 * force-selected because the API refuses an allowlist that no longer covers it.
 *
 * Keeping both derivations in one place is what stops them drifting apart — that drift
 * was the original "dirty on load" bug.
 */
export const getEffectiveModels = (
  stored: string[] | undefined,
  catalog: { value: string }[],
  requiredModel: string,
) => {
  const matched = getPrefixedModels(stored, catalog);
  if (requiredModel && !matched.includes(requiredModel)) {
    matched.push(requiredModel);
  }
  return matched;
};
