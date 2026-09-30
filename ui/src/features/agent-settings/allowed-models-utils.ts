const MODEL_PREFIX = "litellm/openrouter/";

export const stripPrefix = (model: string) => model.replace(/^litellm\/openrouter\//, "");

// Stored allowlists (and the original migration backfill) can hold glob patterns such
// as "*" or "openai/*". Detect them so they can be expanded against the live catalog
// rather than shown as bogus "not in catalog" orphans.
const isGlob = (model: string) => /[*?[\]]/.test(model);

const globToRegExp = (pattern: string) => {
  const escaped = pattern
    .replace(/[.+^${}()|\\]/g, "\\$&")
    .replace(/\*/g, ".*")
    .replace(/\?/g, ".");
  return new RegExp(`^${escaped}$`, "i");
};

// Catalog entries whose bare slug matches a glob pattern, as full prefixed values.
const expandGlob = (pattern: string, catalog: { value: string }[]) => {
  const re = globToRegExp(stripPrefix(pattern).toLowerCase());
  return catalog.map((entry) => entry.value).filter((value) => re.test(stripPrefix(value).toLowerCase()));
};

export const getPrefixedModels = (stored: string[] | undefined, catalog: { value: string }[]) => {
  const catalogValues = new Set(catalog.map((entry) => entry.value));
  const resolved = new Set<string>();
  for (const model of stored || []) {
    if (catalogValues.has(model)) {
      resolved.add(model);
      continue;
    }
    // Handles bare OpenRouter slugs and values like "litellm/gpt-5-mini".
    const withPrefix = `${MODEL_PREFIX}${model}`;
    if (catalogValues.has(withPrefix)) {
      resolved.add(withPrefix);
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
    if (catalogValues.has(model) || catalogValues.has(`${MODEL_PREFIX}${model}`)) return false;
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
