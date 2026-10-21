"use client";

import { Loader2 } from "lucide-react";

import { AppErrorState } from "@/components/app-error-state";
import { SettingsSection } from "@/components/settings/settings-section";

import { useSyncProvidersQuery } from "../hooks/use-sync-providers-query";
import { SyncProviderRow } from "./sync-provider-row";

const TITLE = "Sync";
const DESCRIPTION = "Connect storage providers to keep your organization's files in sync.";

export function SyncProvidersPanel({ canManage }: { canManage: boolean }) {
  const { providers, isLoading, error, refetch } = useSyncProvidersQuery();

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 text-[0.84rem]" style={{ color: "var(--ink-3)" }}>
        <Loader2 size={15} className="animate-spin" /> Loading sync providers…
      </div>
    );
  }
  if (error || !providers) {
    return <AppErrorState error={error} title="We couldn't load sync providers" onRetry={() => void refetch()} />;
  }

  return (
    <SettingsSection title={TITLE} description={DESCRIPTION}>
      {providers.length === 0 ? (
        <p className="m-0 text-[0.84rem]" style={{ color: "var(--ink-3)" }}>
          No sync providers are available on this server.
        </p>
      ) : (
        <ul
          aria-label="Sync providers"
          className="m-0 list-none divide-y p-0"
          style={{ borderColor: "var(--line)" }}
        >
          {providers.map((provider) => (
            <SyncProviderRow key={provider.key} provider={provider} canManage={canManage} />
          ))}
        </ul>
      )}
    </SettingsSection>
  );
}
