"use client";

import { useState } from "react";
import { useDebouncedValue } from "@tanstack/react-pacer";
import { Building, Check, ChevronsUpDown, Loader2 } from "lucide-react";

import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { useInfiniteOrganizations } from "@/features/organizations/hooks/use-infinite-organizations";
import { cn } from "@/lib/utils";

const ORGANIZATION_PAGE_SIZE = 10;
// A little past the visible page height, so the fetch fires slightly before the
// admin actually hits the bottom.
const LOAD_MORE_THRESHOLD_PX = 32;

interface OrganizationComboboxProps {
  organizationId: string | null;
  organizationName: string | null;
  onChange: (organization: { id: string; name: string } | null) => void;
  /** Trigger classes, so the control can match the surrounding toolbar. */
  className?: string;
  /** Trigger width; omit to size to content. */
  width?: string;
  /** Optional. Leave unset so the trigger is named by its current value. */
  ariaLabel?: string;
}

/**
 * Searchable Organization picker over Popover + Command.
 *
 * Pages through the platform Organization list rather than loading it whole,
 * and debounces the search so typing does not fire a request per keystroke.
 */
export function OrganizationCombobox({
  organizationId,
  organizationName,
  onChange,
  className = "af-input",
  width = "13rem",
  ariaLabel,
}: OrganizationComboboxProps) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [debouncedQuery] = useDebouncedValue(query, { wait: 300 });

  const {
    organizations,
    hasNextPage,
    fetchNextPage,
    isFetchingNextPage,
    isLoading,
  } = useInfiniteOrganizations({
    search: debouncedQuery,
    pageSize: ORGANIZATION_PAGE_SIZE,
  });

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-haspopup="listbox"
          aria-expanded={open}
          aria-label={ariaLabel}
          className={cn(className, "flex items-center justify-between gap-2")}
          style={width ? { width } : undefined}
        >
          <span className="truncate flex items-center gap-1.5 min-w-0">
            <Building
              size={13}
              style={{ color: "var(--ink-4)", flexShrink: 0 }}
            />
            <span className="truncate">
              {organizationId
                ? (organizationName ?? "Selected organization")
                : "All organizations"}
            </span>
          </span>
          <ChevronsUpDown
            size={13}
            style={{ color: "var(--ink-4)", flexShrink: 0 }}
          />
        </button>
      </PopoverTrigger>
      <PopoverContent className="w-72 p-0" align="start">
        <Command shouldFilter={false}>
          <CommandInput
            placeholder="Search organizations..."
            value={query}
            onValueChange={setQuery}
          />
          <CommandList
            onScroll={(event) => {
              const el = event.currentTarget;
              const nearBottom =
                el.scrollHeight - el.scrollTop - el.clientHeight <
                LOAD_MORE_THRESHOLD_PX;
              if (nearBottom && hasNextPage && !isFetchingNextPage) {
                void fetchNextPage();
              }
            }}
          >
            {!isLoading && organizations.length === 0 && (
              <CommandEmpty>No organizations found.</CommandEmpty>
            )}
            {/* One group: the reset is the first choice in the list, not a
                section of its own. Two unlabelled groups leave a gap that
                reads as a mistake. */}
            <CommandGroup>
              <CommandItem
                value="__all__"
                onSelect={() => {
                  onChange(null);
                  setOpen(false);
                }}
              >
                <Check
                  className={cn("opacity-0", !organizationId && "opacity-100")}
                />
                All organizations
              </CommandItem>
              {organizations.map((organization) => (
                <CommandItem
                  key={organization.id}
                  value={organization.id}
                  onSelect={() => {
                    onChange({ id: organization.id, name: organization.name });
                    setOpen(false);
                  }}
                >
                  <Check
                    className={cn(
                      "opacity-0",
                      organization.id === organizationId && "opacity-100",
                    )}
                  />
                  <span className="truncate">{organization.name}</span>
                </CommandItem>
              ))}
            </CommandGroup>
            {isFetchingNextPage && (
              <div className="flex items-center gap-1.5 px-2 py-1.5 text-xs text-muted-foreground">
                <Loader2 size={12} className="animate-spin" /> Loading more...
              </div>
            )}
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}
