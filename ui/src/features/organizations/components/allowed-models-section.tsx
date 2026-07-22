"use client";

import { useState, useMemo, useEffect } from "react";
import { Loader2, Search, X } from "lucide-react";

import { useModels } from "@/features/agents/hooks/use-models";
import { useUpdateOrganization } from "../hooks/use-organization-actions";
import { Organization } from "../schemas";

export function AllowedModelsSection({
  organization,
}: {
  organization: Organization;
}) {
  const { models, isLoading } = useModels({ catalog: true });
  const updateOrg = useUpdateOrganization();
  
  const getPrefixedModels = (dbModels: string[] | undefined, catalog: typeof models) => {
    const catalogValues = new Set(catalog.map((c) => c.value));
    return (dbModels || [])
      .map((m) => {
        // Already in the correct prefixed form
        if (catalogValues.has(m)) return m;
        // Try adding the prefix (handles bare OpenRouter slugs like "kwaipilot/..." and
        // also models like "litellm/gpt-5-mini" whose catalog value is
        // "litellm/openrouter/litellm/gpt-5-mini")
        const withPrefix = `litellm/openrouter/${m}`;
        if (catalogValues.has(withPrefix)) return withPrefix;
        // Unknown / truly orphaned value — discard
        return null;
      })
      .filter((m): m is string => m !== null);
  };

  const [selectedModels, setSelectedModels] = useState<string[]>(() => {
    const initial = getPrefixedModels(organization.allowedModels, models);
    const def = models.find((m) => m.isDefault);
    if (def && !initial.includes(def.value)) {
      return [...initial, def.value];
    }
    return initial;
  });
  const [searchQuery, setSearchQuery] = useState("");

  useEffect(() => {
    if (!isLoading) {
      const dbModels = getPrefixedModels(organization.allowedModels, models);
      const def = models.find((m) => m.isDefault);
      if (def && !dbModels.includes(def.value)) {
        dbModels.push(def.value);
      }
      setSelectedModels(dbModels);
    }
  }, [organization.allowedModels, models, isLoading]);

  const filteredModels = useMemo(() => {
    if (!searchQuery) return models;
    const query = searchQuery.toLowerCase();
    return models.filter(
      (model) =>
        model.label.toLowerCase().includes(query) ||
        model.value.toLowerCase().includes(query),
    );
  }, [models, searchQuery]);

  const toggleModel = (value: string) => {
    const isDefault = models.find((m) => m.value === value)?.isDefault;
    if (isDefault) return;
    setSelectedModels((prev) =>
      prev.includes(value) ? prev.filter((m) => m !== value) : [...prev, value],
    );
  };

  const handleSave = () => {
    const cleaned = selectedModels.map((m) =>
      m.replace("litellm/openrouter/", "")
    );
    updateOrg.mutate({
      organizationId: organization.id,
      data: { allowedModels: cleaned },
    });
  };

  const isDirty =
    JSON.stringify([...selectedModels].sort()) !==
    JSON.stringify([...getPrefixedModels(organization.allowedModels, models)].sort());

  return (
    <div className="pt-6">
      <div className="flex items-center justify-between mb-4">
        <div className="mr-8">
          <h2
            className="text-[15px] font-semibold"
            style={{ color: "var(--ink)" }}
          >
            Allowed Models
          </h2>
          <p className="text-[13.5px] mt-1" style={{ color: "var(--ink-3)" }}>
            Select which LLMs are available to agents in this organization. The default model ({models.find(m => m.isDefault)?.label || "GLM 5.2"}) is automatically selected and required. If none are selected, agents cannot be created.
          </p>
        </div>
        <button
          className="af-btn af-btn-primary flex-shrink-0"
          disabled={!isDirty || updateOrg.isPending}
          onClick={handleSave}
        >
          {updateOrg.isPending ? "Saving…" : "Save changes"}
        </button>
      </div>

      <div className="af-card p-4">
        {isLoading ? (
          <div
            className="flex items-center gap-2 text-[13.5px]"
            style={{ color: "var(--ink-3)" }}
          >
            <Loader2 width={15} height={15} className="animate-spin" /> Loading
            model catalog…
          </div>
        ) : (
          <>
            {selectedModels.length > 0 && (
              <div className="flex flex-wrap gap-2 mb-4">
                {selectedModels.map((value) => {
                  const model = models.find((m) => m.value === value);
                  return (
                    <div
                      key={value}
                      className="flex items-center gap-1.5 px-2.5 py-1 text-[13px] bg-neutral-100 border border-neutral-200 rounded-md"
                    >
                      <span className="text-neutral-700">
                        {model ? model.label : value}
                      </span>
                      {!(model?.isDefault) && (
                        <button
                          type="button"
                          onClick={() => toggleModel(value)}
                          className="text-neutral-400 hover:text-neutral-700"
                        >
                          <X width={14} height={14} />
                        </button>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
            <div className="relative mb-3">
              <Search
                className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400"
                width={16}
                height={16}
              />
              <input
                type="text"
                placeholder="Search models..."
                className="w-full pl-9 pr-3 py-2 text-[13.5px] border border-gray-200 rounded-md focus:outline-none focus:ring-1 focus:ring-gray-300"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
              />
            </div>
            <div className="flex flex-col gap-2 max-h-[300px] overflow-y-auto">
              {filteredModels.map((model) => {
                const isSelected = selectedModels.includes(model.value);
                return (
                  <label
                    key={model.value}
                    className="flex items-center gap-3 p-2 rounded-md cursor-pointer hover:bg-neutral-100"
                    style={{ transition: "background 0.2s" }}
                  >
                    <input
                      type="checkbox"
                      className="w-4 h-4 rounded border-gray-300 disabled:opacity-50 disabled:cursor-not-allowed"
                      style={{ accentColor: "var(--ink)" }}
                      checked={isSelected}
                      disabled={model.isDefault}
                      onChange={() => toggleModel(model.value)}
                    />
                    <div className="flex flex-col">
                      <span
                        className="text-[13.5px] font-medium"
                        style={{ color: "var(--ink)" }}
                      >
                        {model.label}
                        {model.isDefault && (
                          <span className="ml-2 text-[11px] text-neutral-500 font-normal bg-neutral-100 px-1.5 py-0.5 rounded border border-neutral-200">
                            Default (required)
                          </span>
                        )}
                      </span>
                      <span
                        className="text-[12px]"
                        style={{ color: "var(--ink-3)" }}
                      >
                        {model.value}
                      </span>
                    </div>
                  </label>
                );
              })}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
