"use client";

import { useId, useState } from "react";
import { useDebouncedValue } from "@tanstack/react-pacer";
import { Loader2 } from "lucide-react";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useInfiniteOrganizations } from "@/features/organizations/hooks/use-infinite-organizations";

import {
  useLlmProviderOrganizationActions,
  useLlmProviderOrganizations,
} from "../hooks/use-llm-provider-organizations";
import type { LlmProviderConnection, LlmProviderOrganizations, OrganizationAccess } from "../schemas";
import { failureMessage, providerTitle, returnFocusTo as focusOnClose } from "../utils";

const ERROR = { color: "var(--err)" };
const MUTED = { color: "var(--ink-3)" };
const SEARCH_WAIT_MS = 300;
const ACCESS_OPTIONS: { value: OrganizationAccess; label: string }[] = [
  { value: "all", label: "All organizations" },
  { value: "none", label: "No organizations" },
  { value: "all_except", label: "All organizations except the ticked ones" },
  { value: "only", label: "Only the ticked organizations" },
];
const LISTING_ACCESS: OrganizationAccess[] = ["all_except", "only"];

type Organization = { id: string; name: string };

export type OrganizationAccessState = ReturnType<typeof useOrganizationAccess>;

export function useOrganizationAccess(initialAccess: OrganizationAccess, initialOrganizations: Organization[]) {
  const [access, setAccess] = useState<OrganizationAccess>(initialAccess);
  const [ticked, setTicked] = useState(
    () => new Map(initialOrganizations.map((organization) => [organization.id, organization.name])),
  );
  const [storedTicked] = useState(initialOrganizations);
  const listsOrganizations = LISTING_ACCESS.includes(access);

  function toggle(organization: Organization) {
    setTicked((current) => {
      const next = new Map(current);
      if (next.has(organization.id)) next.delete(organization.id);
      else next.set(organization.id, organization.name);
      return next;
    });
  }

  return {
    access,
    setAccess,
    ticked,
    storedTicked,
    toggle,
    listsOrganizations,
    organizationIds: listsOrganizations ? [...ticked.keys()] : [],
  };
}

export function OrganizationAccessFields({
  state,
  legend,
  showLegend = false,
}: {
  state: OrganizationAccessState;
  legend: string;
  showLegend?: boolean;
}) {
  const groupName = useId();

  return (
    <>
      <fieldset className="m-0 flex flex-col gap-2 border-0 p-0">
        <legend
          className={showLegend ? "mb-1 p-0 text-[0.8rem] font-medium" : "sr-only"}
          style={showLegend ? { color: "var(--ink-2)" } : undefined}
        >
          {legend}
        </legend>
        {ACCESS_OPTIONS.map((option) => (
          <label key={option.value} className="flex items-center gap-2.5 text-sm">
            <input
              type="radio"
              name={groupName}
              style={{ accentColor: "var(--ink)" }}
              checked={state.access === option.value}
              onChange={() => state.setAccess(option.value)}
            />
            {option.label}
          </label>
        ))}
      </fieldset>
      {state.listsOrganizations && (
        <OrganizationChecklist ticked={state.ticked} storedTicked={state.storedTicked} onToggle={state.toggle} />
      )}
    </>
  );
}

export function ProviderOrganizationsDialog({
  connection,
  open,
  onOpenChange,
  onSaved,
  returnFocusTo,
}: {
  connection: LlmProviderConnection;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSaved: () => void;
  /** Focused when the dialog closes; see `returnFocusTo` in utils. */
  returnFocusTo?: HTMLElement | null;
}) {
  const {
    providerOrganizations,
    isLoadingProviderOrganizations,
    providerOrganizationsError,
    reloadProviderOrganizations,
  } = useLlmProviderOrganizations(connection.slug, open);
  const title = providerTitle(connection);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex max-h-[85vh] flex-col sm:max-w-lg" onCloseAutoFocus={focusOnClose(returnFocusTo)}>
        <DialogHeader>
          <DialogTitle>{title} organizations</DialogTitle>
          <DialogDescription>
            Choose which Organizations may use {title}. All organizations, and all except the ticked ones, also
            cover Organizations created later.
          </DialogDescription>
        </DialogHeader>
        {isLoadingProviderOrganizations ? (
          <p role="status" className="m-0 text-sm">
            Loading organizations…
          </p>
        ) : providerOrganizationsError || !providerOrganizations ? (
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="m-0 text-[0.8rem]" style={ERROR} role="alert">
              {failureMessage(providerOrganizationsError)}
            </p>
            <button type="button" className="af-btn af-btn-sm" onClick={() => void reloadProviderOrganizations()}>
              Retry
            </button>
          </div>
        ) : (
          <OrganizationsForm
            connection={connection}
            initial={providerOrganizations}
            onCancel={() => onOpenChange(false)}
            onSaved={onSaved}
          />
        )}
      </DialogContent>
    </Dialog>
  );
}

function OrganizationsForm({
  connection,
  initial,
  onCancel,
  onSaved,
}: {
  connection: LlmProviderConnection;
  initial: LlmProviderOrganizations;
  onCancel: () => void;
  onSaved: () => void;
}) {
  const { saveOrganizations, isSavingOrganizations, saveOrganizationsError } = useLlmProviderOrganizationActions(
    connection.slug,
  );
  const state = useOrganizationAccess(initial.organizationAccess, initial.organizations);

  async function save() {
    await saveOrganizations({ organizationAccess: state.access, organizationIds: state.organizationIds })
      .then(onSaved)
      .catch(() => undefined);
  }

  return (
    <form
      className="flex min-h-0 flex-1 flex-col gap-4"
      onSubmit={(event) => {
        event.preventDefault();
        void save();
      }}
    >
      <OrganizationAccessFields state={state} legend={`Who may use ${providerTitle(connection)}`} />
      {saveOrganizationsError ? (
        <p className="m-0 text-[0.8rem]" style={ERROR} role="alert">
          {failureMessage(saveOrganizationsError)}
        </p>
      ) : null}
      <DialogFooter>
        <button type="button" className="af-btn" onClick={onCancel}>
          Cancel
        </button>
        <button type="submit" className="af-btn af-btn-primary" disabled={isSavingOrganizations}>
          {isSavingOrganizations && <Loader2 size={14} className="animate-spin" />} Save organizations
        </button>
      </DialogFooter>
    </form>
  );
}

function OrganizationChecklist({
  ticked,
  storedTicked,
  onToggle,
}: {
  ticked: Map<string, string>;
  storedTicked: Organization[];
  onToggle: (organization: Organization) => void;
}) {
  const [search, setSearch] = useState("");
  const [debouncedSearch] = useDebouncedValue(search, { wait: SEARCH_WAIT_MS });
  const { organizations, hasNextPage, fetchNextPage, isFetchingNextPage, isLoading, error, refetch } =
    useInfiniteOrganizations({ search: debouncedSearch });
  const pinned = debouncedSearch.trim() ? [] : storedTicked;
  const pinnedIds = new Set(pinned.map((organization) => organization.id));
  const listed = [...pinned, ...organizations.filter((organization) => !pinnedIds.has(organization.id))];

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-2">
      <div className="flex items-center gap-3">
        <input
          className="af-input w-full"
          aria-label="Search organizations"
          placeholder="Search organizations…"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
        <span className="shrink-0 text-[0.8rem]" style={MUTED}>
          {ticked.size} ticked
        </span>
      </div>
      {isLoading ? (
        <p role="status" className="m-0 text-sm">
          Loading organizations…
        </p>
      ) : error ? (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="m-0 text-[0.8rem]" style={ERROR} role="alert">
            {failureMessage(error)}
          </p>
          <button type="button" className="af-btn af-btn-sm" onClick={() => void refetch()}>
            Retry
          </button>
        </div>
      ) : listed.length === 0 ? (
        <p className="m-0 text-sm" style={MUTED}>
          No organizations match.
        </p>
      ) : (
        <ul aria-label="Organizations" className="m-0 max-h-64 min-h-0 list-none overflow-y-auto p-0">
          {listed.map((organization) => (
            <li key={organization.id}>
              <label className="flex items-center gap-2.5 py-1 text-sm">
                <input
                  type="checkbox"
                  style={{ accentColor: "var(--ink)" }}
                  checked={ticked.has(organization.id)}
                  onChange={() => onToggle(organization)}
                />
                {organization.name}
              </label>
            </li>
          ))}
        </ul>
      )}
      {hasNextPage && (
        <button
          type="button"
          className="af-btn af-btn-sm self-start"
          disabled={isFetchingNextPage}
          onClick={() => void fetchNextPage()}
        >
          Show more
        </button>
      )}
    </div>
  );
}
