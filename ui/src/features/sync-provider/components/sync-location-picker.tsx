"use client";

import { useState } from "react";
import { Loader2 } from "lucide-react";

import { useChooseSyncLocation, useSyncLocations } from "../hooks/use-sync-provider-actions";
import type { SyncProvider } from "../schemas";

/** Finishes a pending connection: search the signed-in person's locations and pick one. */
export function SyncLocationPicker({ provider, noun }: { provider: SyncProvider; noun: string }) {
  const [draft, setDraft] = useState("");
  const [search, setSearch] = useState("");
  const [error, setError] = useState<string | null>(null);
  const { locations, isSearching, error: searchError } = useSyncLocations(provider, search);
  const { chooseLocation, isChoosing } = useChooseSyncLocation(provider);

  async function handleChoose(locationId: string) {
    setError(null);
    try {
      await chooseLocation(locationId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Connecting the location failed.");
    }
  }

  const shownError = error ?? (searchError instanceof Error ? searchError.message : null);

  return (
    <div className="flex flex-col gap-3">
      <p className="m-0 text-[0.84rem] leading-[1.5]" style={{ color: "var(--ink-3)" }}>
        Pick the {noun} where Agent Barn keeps its folder. Search by part of its name.
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
          aria-label={`Search ${noun}s`}
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

      {locations && locations.length === 0 && search && !isSearching && (
        <p className="m-0 text-[0.84rem]" style={{ color: "var(--ink-3)" }}>
          Nothing matches &ldquo;{search}&rdquo;.
        </p>
      )}

      {locations && locations.length > 0 && (
        <ul className="m-0 flex list-none flex-col gap-2 p-0">
          {locations.map((location) => (
            <li
              key={location.id}
              className="flex items-center gap-3 rounded-lg border px-3 py-2"
              style={{ borderColor: "var(--line)" }}
            >
              <div className="min-w-0 flex-1">
                <div className="text-[0.88rem] font-medium" style={{ color: "var(--ink)" }}>
                  {location.name}
                </div>
                <div className="truncate text-[0.78rem]" style={{ color: "var(--ink-3)" }}>
                  {location.webUrl}
                </div>
              </div>
              <button
                type="button"
                className="af-btn af-btn-primary af-btn-sm"
                aria-label={`Use ${location.name}`}
                disabled={isChoosing}
                onClick={() => void handleChoose(location.id)}
              >
                Use
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
