"use client";

import { useMemo } from "react";
import { useQueries } from "@tanstack/react-query";

import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";
import { api } from "@/shared/api";

import {
  AgentTemplateRead,
  TemplateVersionsSchema,
  type AgentConfigurationVersion,
  type AgentOverrideVersion,
} from "../schemas";
import {
  templateSelectionValue,
  type TemplateSelectionOption,
} from "../components/agent-configuration-utils";
import { templatesKey } from "../utils";

function templateTypeLabel(
  template: Pick<AgentTemplateRead, "organizationId" | "forkedFromPlatformTemplateId">,
): TemplateSelectionOption["typeLabel"] {
  if (template.organizationId === null) return "Built-in platform";
  if (template.forkedFromPlatformTemplateId) return "Organization fork";
  return "Organization-owned";
}

function sharedSelectionType(template: Pick<AgentTemplateRead, "organizationId">): "platform" | "organization" {
  return template.organizationId === null ? "platform" : "organization";
}

export function useAgentTemplateSelectionOptions({
  templates,
  active,
  overrideVersions,
  sourceUpdate,
}: {
  templates: AgentTemplateRead[];
  active: AgentConfigurationVersion;
  overrideVersions: AgentOverrideVersion[];
  sourceUpdate?: AgentConfigurationVersion | null;
}) {
  const orgApiBase = useOrganizationApiBase();
  const templateKeys = useMemo(
    () => Array.from(new Set(templates.map((template) => template.templateKey))),
    [templates],
  );
  const versionQueries = useQueries({
    queries: templateKeys.map((templateKey) => ({
      queryKey: [...templatesKey.detail(templateKey), "versions"],
      queryFn: async (): Promise<AgentTemplateRead[]> => {
        const response = await api.get<AgentTemplateRead[]>(
          `${orgApiBase}/templates/${templateKey}/versions`,
          { schema: TemplateVersionsSchema },
        );
        return response.data;
      },
    })),
  });

  const sharedVersions = versionQueries.flatMap((query) => query.data ?? []);
  const isLoading = versionQueries.some((query) => query.isPending);
  const hasError = versionQueries.some((query) => query.isError);

  const options = useMemo(() => {
    const allSharedVersions = [...templates, ...sharedVersions];
    const latestByLineage = new Map<string, number>();
    for (const template of allSharedVersions) {
      const selectionType = sharedSelectionType(template);
      const lineage = `${selectionType}:${template.templateKey}`;
      latestByLineage.set(
        lineage,
        Math.max(latestByLineage.get(lineage) ?? 0, template.version),
      );
    }

    const sharedOptionsByValue = new Map<string, TemplateSelectionOption>();
    for (const template of allSharedVersions) {
      const selectionType = sharedSelectionType(template);
      const value = templateSelectionValue(
        selectionType,
        template.templateKey,
        template.version,
      );
      const isSourceUpdate =
        sourceUpdate?.sourceType === selectionType &&
        sourceUpdate.sourceTemplateKey === template.templateKey &&
        sourceUpdate.sourceTemplateVersion === template.version;
      sharedOptionsByValue.set(value, {
        value,
        selectionType,
        templateKey: template.templateKey,
        templateVersion: template.version,
        snapshot: template,
        typeLabel: templateTypeLabel(template),
        name: template.templateName,
        version: template.version,
        updatedAt: template.updatedAt,
        isLatest:
          template.version ===
          latestByLineage.get(`${selectionType}:${template.templateKey}`),
        platformUpdateAvailable: template.platformUpdateAvailable,
        sourceUpdateAvailable: isSourceUpdate,
        searchText: [
          templateTypeLabel(template),
          template.templateName,
          template.templateKey,
          `version ${template.version}`,
          template.description ?? "",
          template.platformUpdateAvailable ? "platform update available" : "",
          isSourceUpdate ? `${selectionType} update available` : "",
        ].join(" "),
      });
    }

    if (sourceUpdate) {
      const selectionType = sourceUpdate.sourceType;
      const value = templateSelectionValue(
        selectionType,
        sourceUpdate.sourceTemplateKey,
        sourceUpdate.sourceTemplateVersion,
      );
      const existing = sharedOptionsByValue.get(value);
      if (existing) {
        existing.sourceUpdateAvailable = true;
        existing.searchText = `${existing.searchText} ${selectionType} update available`;
      } else {
        const typeLabel: TemplateSelectionOption["typeLabel"] =
          selectionType === "platform"
            ? "Built-in platform"
            : sourceUpdate.sourcePlatformTemplateId
              ? "Organization fork"
              : "Organization-owned";
        sharedOptionsByValue.set(value, {
          value,
          selectionType,
          templateKey: sourceUpdate.sourceTemplateKey,
          templateVersion: sourceUpdate.sourceTemplateVersion,
          snapshot: sourceUpdate,
          typeLabel,
          name: sourceUpdate.templateName,
          version: sourceUpdate.sourceTemplateVersion,
          updatedAt: sourceUpdate.updatedAt,
          isLatest: true,
          platformUpdateAvailable: false,
          sourceUpdateAvailable: true,
          searchText: [
            typeLabel,
            `${selectionType} update available`,
            sourceUpdate.templateName,
            sourceUpdate.sourceTemplateKey,
            `version ${sourceUpdate.sourceTemplateVersion}`,
            sourceUpdate.description ?? "",
          ].join(" "),
        });
      }
    }

    const latestOverrideVersion = overrideVersions.reduce(
      (latest, version) => Math.max(latest, version.version),
      0,
    );
    const overrideOptions = overrideVersions.map<TemplateSelectionOption>((version) => {
      const value = templateSelectionValue("override", undefined, version.version);
      return {
        value,
        selectionType: "override",
        overrideVersion: version.version,
        snapshot: version,
        typeLabel: "Agent override",
        name: version.templateName,
        version: version.version,
        updatedAt: version.updatedAt,
        isLatest: version.version === latestOverrideVersion,
        platformUpdateAvailable: false,
        sourceUpdateAvailable: false,
        searchText: [
          "Agent override",
          version.templateName,
          version.sourceTemplateKey,
          `version ${version.version}`,
          version.description ?? "",
        ].join(" "),
      };
    });

    const allOptions = [
      ...Array.from(sharedOptionsByValue.values()),
      ...overrideOptions,
    ];
    const activeValue =
      active.pinType === "override"
        ? templateSelectionValue("override", undefined, active.version ?? undefined)
        : templateSelectionValue(
            active.sourceType,
            active.sourceTemplateKey,
            active.sourceTemplateVersion,
          );

    if (!allOptions.some((option) => option.value === activeValue)) {
      const typeLabel =
        active.pinType === "override"
          ? "Agent override"
          : active.sourceType === "platform"
            ? "Built-in platform"
            : "Organization-owned";
      const version =
        active.pinType === "override"
          ? active.version ?? active.sourceTemplateVersion
          : active.sourceTemplateVersion;
      allOptions.push({
        value: activeValue,
        selectionType: active.pinType === "override" ? "override" : active.sourceType,
        templateKey:
          active.pinType === "override" ? undefined : active.sourceTemplateKey,
        templateVersion:
          active.pinType === "override" ? undefined : active.sourceTemplateVersion,
        overrideVersion: active.pinType === "override" ? active.version ?? undefined : undefined,
        snapshot: active,
        typeLabel,
        name: active.templateName,
        version,
        updatedAt: active.updatedAt,
        isLatest: false,
        platformUpdateAvailable: false,
        sourceUpdateAvailable: false,
        searchText: [
          typeLabel,
          active.templateName,
          active.sourceTemplateKey,
          `version ${version}`,
          active.description ?? "",
        ].join(" "),
      });
    }

    const typeOrder: Record<TemplateSelectionOption["typeLabel"], number> = {
      "Built-in platform": 0,
      "Organization fork": 1,
      "Organization-owned": 2,
      "Agent override": 3,
    };
    return allOptions.sort(
      (left, right) =>
        (Date.parse(right.updatedAt) || 0) - (Date.parse(left.updatedAt) || 0) ||
        typeOrder[left.typeLabel] - typeOrder[right.typeLabel] ||
        left.name.localeCompare(right.name) ||
        right.version - left.version,
    );
  }, [active, overrideVersions, sharedVersions, sourceUpdate, templates]);

  return { options, isLoading, hasError };
}
