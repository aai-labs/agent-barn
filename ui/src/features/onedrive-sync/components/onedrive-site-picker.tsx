"use client";

import { useState } from "react";
import { Loader2 } from "lucide-react";

import { useChooseOneDriveSite, useOneDriveSyncSites } from "../hooks/use-onedrive-sync-actions";

/** Finishes a pending connection: search the signed-in administrator's sites and pick one. */
export function OneDriveSitePicker() {
  const [draft, setDraft] = useState("");
  const [search, setSearch] = useState("");
  const [error, setError] = useState<string | null>(null);
  const { sites, isSearching, error: searchError } = useOneDriveSyncSites(search);
  const { chooseSite, isChoosing } = useChooseOneDriveSite();

  async function handleChoose(siteId: string) {
    setError(null);
    try {
      await chooseSite(siteId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Connecting the site failed.");
    }
  }

  const shownError = error ?? (searchError instanceof Error ? searchError.message : null);

  return (
    <div className="flex flex-col gap-3">
      <p className="m-0 text-[0.84rem] leading-[1.5]" style={{ color: "var(--ink-3)" }}>
        Pick the SharePoint site where Agent Barn keeps its folder. Search by part of the site&apos;s name.
      </p>
      <form
        className="flex items-center gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          setError(null);
          setSearch(draft.trim());
        }}
      >
        <input
          className="af-input flex-1"
          aria-label="Search SharePoint sites"
          placeholder="e.g. Marketing"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
        />
        <button type="submit" className="af-btn af-btn-ghost" disabled={!draft.trim() || isSearching}>
          Search
        </button>
      </form>

      {isSearching && (
        <div className="flex items-center gap-2 text-[0.84rem]" style={{ color: "var(--ink-3)" }}>
          <Loader2 size={15} className="animate-spin" /> Searching…
        </div>
      )}

      {shownError && (
        <p role="alert" className="m-0 text-[0.84rem]" style={{ color: "var(--err)" }}>
          {shownError}
        </p>
      )}

      {sites && sites.length === 0 && search && !isSearching && (
        <p className="m-0 text-[0.84rem]" style={{ color: "var(--ink-3)" }}>
          No sites match &ldquo;{search}&rdquo;.
        </p>
      )}

      {sites && sites.length > 0 && (
        <ul className="m-0 flex list-none flex-col gap-2 p-0">
          {sites.map((site) => (
            <li
              key={site.id}
              className="flex items-center gap-3 rounded-lg border px-3 py-2"
              style={{ borderColor: "var(--line)" }}
            >
              <div className="min-w-0 flex-1">
                <div className="text-[0.88rem] font-medium" style={{ color: "var(--ink)" }}>
                  {site.name}
                </div>
                <div className="truncate text-[0.78rem]" style={{ color: "var(--ink-3)" }}>
                  {site.webUrl}
                </div>
              </div>
              <button
                type="button"
                className="af-btn af-btn-primary af-btn-sm"
                aria-label={`Use ${site.name}`}
                disabled={isChoosing}
                onClick={() => void handleChoose(site.id)}
              >
                Use this site
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
