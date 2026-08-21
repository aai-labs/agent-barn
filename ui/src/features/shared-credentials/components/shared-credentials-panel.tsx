"use client";

import { useState } from "react";
import { ChevronDownIcon } from "lucide-react";

import { AppErrorState } from "@/components/app-error-state";
import { KeyIcon, PlusIcon } from "@/components/icons";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Pagination } from "@/features/agents/components/pagination";
import { useActiveOrgRole } from "@/features/organizations/hooks/use-active-org-role";

import type { SharedCredentialRead } from "../schemas";
import { useSharedCredentials } from "../hooks/use-shared-credentials";
import {
  SHARED_CREDENTIALS_PAGE_SIZE,
  SHARED_CREDENTIAL_PROVIDER_LABELS,
  SHARED_CREDENTIAL_PROVIDERS,
} from "../utils";
import { SharedCredentialDrawer } from "./shared-credential-drawer";
import { SettingsHint } from "@/components/settings/settings-hint";

const PROVIDER_FILTERS: Array<{ value: string; label: string }> = [
  { value: "", label: "All providers" },
  ...SHARED_CREDENTIAL_PROVIDERS,
];

type DrawerMode =
  | { kind: "create" }
  | { kind: "view"; credential: SharedCredentialRead };

function ProviderBadge({ provider }: { provider: string }) {
  return (
    <span
      className="inline-flex items-center px-2 py-0.5 rounded-md text-[0.7rem] font-medium"
      style={{
        background: "var(--bg-soft)",
        color: "var(--ink-3)",
        border: "1px solid var(--line)",
      }}
    >
      {SHARED_CREDENTIAL_PROVIDER_LABELS[provider] ?? provider}
    </span>
  );
}

export function SharedCredentialsPanel() {
  const [search, setSearch] = useState("");
  const [providerFilter, setProviderFilter] = useState("");
  const [page, setPage] = useState(1);
  const [drawer, setDrawer] = useState<DrawerMode | null>(null);
  const { canManage } = useActiveOrgRole();

  const { credentials, total, isLoading, error, refetch } =
    useSharedCredentials({
      search: search || undefined,
      provider: providerFilter || undefined,
      page,
    });

  const totalPages = Math.max(
    1,
    Math.ceil(total / SHARED_CREDENTIALS_PAGE_SIZE),
  );

  function handleSearchChange(value: string) {
    setSearch(value);
    setPage(1);
  }

  function handleProviderChange(value: string) {
    setProviderFilter(value);
    setPage(1);
  }

  return (
    <>
      <SettingsHint>
        <KeyIcon style={{ flexShrink: 0, marginTop: 1 }} />
        Shared credentials are org-wide integration keys that admins create once.
        Any member can attach them to their agents instead of entering credentials manually.
      </SettingsHint>

      <div className="af-card p-5">
        <div className="mb-4 flex items-center gap-2.5">
          <div className="relative flex-1">
            <input
              className="af-input w-full"
              placeholder="Search credentials…"
              aria-label="Search shared credentials"
              value={search}
              onChange={(e) => handleSearchChange(e.target.value)}
            />
          </div>
          <div className="flex-1">
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <button
                  className="af-input w-full flex items-center gap-2 whitespace-nowrap"
                  aria-label="Filter by provider"
                >
                  {PROVIDER_FILTERS.find((f) => f.value === providerFilter)
                    ?.label ?? "All providers"}
                  <ChevronDownIcon
                    size={13}
                    className="opacity-50 flex-shrink-0"
                  />
                </button>
              </DropdownMenuTrigger>
              <DropdownMenuContent>
                <DropdownMenuRadioGroup
                  value={providerFilter}
                  onValueChange={handleProviderChange}
                >
                  {PROVIDER_FILTERS.map((f) => (
                    <DropdownMenuRadioItem key={f.value} value={f.value}>
                      {f.label}
                    </DropdownMenuRadioItem>
                  ))}
                </DropdownMenuRadioGroup>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
          {canManage && (
            <button
              className="af-btn af-btn-primary ml-auto"
              onClick={() => setDrawer({ kind: "create" })}
            >
              <PlusIcon /> Connect credential
            </button>
          )}
        </div>

        {isLoading && (
          <div
            className="py-8 text-center text-[0.8rem]"
            style={{ color: "var(--ink-3)" }}
          >
            Loading credentials…
          </div>
        )}
        {error && (
          <AppErrorState
            error={error}
            title="We couldn't load shared credentials"
            description="The credentials list is unavailable right now."
            onRetry={() => {
              void refetch();
            }}
            retryLabel="Retry"
          />
        )}
        {!isLoading &&
          !error &&
          credentials.length === 0 &&
          total === 0 &&
          !search &&
          !providerFilter && (
            <div
              className="flex flex-col items-center justify-center text-center py-10 rounded-2xl"
              style={{
                border: "1px dashed var(--line-strong)",
                color: "var(--ink-3)",
              }}
            >
              <div
                className="font-medium text-[0.9375rem] mb-1"
                style={{ color: "var(--ink)" }}
              >
                No shared credentials yet
              </div>
              <div className="text-[0.844rem]">
                {canManage
                  ? "Create your first shared credential to get started."
                  : "An admin can create shared credentials for this organization."}
              </div>
            </div>
          )}
        {!isLoading &&
          !error &&
          credentials.length === 0 &&
          (search || providerFilter) && (
            <div
              className="py-8 text-center text-[0.8rem]"
              style={{ color: "var(--ink-3)" }}
            >
              No credentials match.
            </div>
          )}

        {credentials.map((cred) => (
          <div
            key={cred.id}
            className="flex items-center gap-3 px-0 py-3.5"
            style={{ borderBottom: "1px solid var(--line)" }}
          >
            <div className="flex-1 min-w-0">
              <div
                className="font-medium text-[0.875rem] flex items-center gap-2"
                style={{ color: "var(--ink)" }}
              >
                <span>{cred.name}</span>
                <ProviderBadge provider={cred.provider} />
              </div>
              <div className="text-[0.78rem] mt-0.5" style={{ color: "var(--ink-3)" }}>
                {cred.agentCount === 0
                  ? "Not used by any agents"
                  : cred.agentCount === 1
                    ? "Used by 1 agent"
                    : `Used by ${cred.agentCount} agents`}
              </div>
            </div>
            <button
              className="af-btn af-btn-sm af-btn-ghost"
              onClick={() => setDrawer({ kind: "view", credential: cred })}
            >
              View
            </button>
          </div>
        ))}

        <div className="pt-4">
          <Pagination page={page} totalPages={totalPages} onPageChange={setPage} />
        </div>
      </div>

      {drawer && (
        <SharedCredentialDrawer
          mode={drawer}
          onClose={() => setDrawer(null)}
        />
      )}
    </>
  );
}
