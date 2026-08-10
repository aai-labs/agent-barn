import type { ReactNode } from "react";

import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

import {
  PLATFORM_TEMPLATE_FILES,
  type PlatformTemplateFileKey,
} from "../utils";

type PlatformTemplateArtifact = (typeof PLATFORM_TEMPLATE_FILES)[number];

export function PlatformTemplateArtifactTabs({
  value,
  onValueChange,
  renderContent,
}: {
  value: PlatformTemplateFileKey;
  onValueChange: (value: PlatformTemplateFileKey) => void;
  renderContent: (artifact: PlatformTemplateArtifact) => ReactNode;
}) {
  return (
    <Tabs
      value={value}
      onValueChange={(nextValue) =>
        onValueChange(nextValue as PlatformTemplateFileKey)
      }
      className="w-full min-w-0"
    >
      <TabsList
        variant="default"
        className="h-auto! w-full max-w-full justify-start gap-1.5 overflow-x-auto overflow-y-hidden rounded-2xl border border-border px-1.5 py-1"
      >
        {PLATFORM_TEMPLATE_FILES.map(({ key, label }) => (
          <TabsTrigger
            key={key}
            value={key}
            className="h-auto! flex-none rounded-xl border border-transparent px-3 py-1.5 data-[state=active]:border-input"
          >
            {label}
          </TabsTrigger>
        ))}
      </TabsList>
      {PLATFORM_TEMPLATE_FILES.map((artifact) => (
        <TabsContent key={artifact.key} value={artifact.key} className="mt-5">
          {renderContent(artifact)}
        </TabsContent>
      ))}
    </Tabs>
  );
}
