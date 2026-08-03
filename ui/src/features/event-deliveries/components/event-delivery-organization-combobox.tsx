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
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { useInfiniteOrganizations } from "@/features/organizations/hooks/use-infinite-organizations";
import { cn } from "@/lib/utils";

const ORGANIZATION_PAGE_SIZE = 10;
// A little past the visible page height, so the fetch fires slightly before the
// admin actually hits the bottom.
const LOAD_MORE_THRESHOLD_PX = 32;

interface EventDeliveryOrganizationComboboxProps {
  organizationId: string | null;
  organizationName: string | null;
  onChange: (organization: { id: string; name: string } | null) => void;
}

export function EventDeliveryOrganizationCombobox({
  organizationId,
  organizationName,
  onChange,
}: EventDeliveryOrganizationComboboxProps) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [debouncedQuery] = useDebouncedValue(query, { wait: 300 });

  const { organizations, hasNextPage, fetchNextPage, isFetchingNextPage, isLoading } = useInfiniteOrganizations({
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
          className="af-input flex items-center justify-between gap-2"
          style={{ width: "13rem" }}
        >
          <span className="truncate flex items-center gap-1.5 min-w-0">
            <Building size={13} style={{ color: "var(--ink-4)", flexShrink: 0 }} />
            <span className="truncate">
              {organizationId ? (organizationName ?? "Selected organization") : "All organizations"}
            </span>
          </span>
          <ChevronsUpDown size={13} style={{ color: "var(--ink-4)", flexShrink: 0 }} />
        </button>
      </PopoverTrigger>
      <PopoverContent className="w-72 p-0" align="start">
        <Command shouldFilter={false}>
          <CommandInput placeholder="Search organizations..." value={query} onValueChange={setQuery} />
          <CommandList
            onScroll={(event) => {
              const el = event.currentTarget;
              const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < LOAD_MORE_THRESHOLD_PX;
              if (nearBottom && hasNextPage && !isFetchingNextPage) {
                void fetchNextPage();
              }
            }}
          >
            {!isLoading && organizations.length === 0 && (
              <CommandEmpty>No organizations found.</CommandEmpty>
            )}
            <CommandGroup>
              <CommandItem
                value="__all__"
                onSelect={() => {
                  onChange(null);
                  setOpen(false);
                }}
              >
                <Check className={cn("opacity-0", !organizationId && "opacity-100")} />
                All organizations
              </CommandItem>
            </CommandGroup>
            <CommandGroup>
              {organizations.map((organization) => (
                <CommandItem
                  key={organization.id}
                  value={organization.id}
                  onSelect={() => {
                    onChange({ id: organization.id, name: organization.name });
                    setOpen(false);
                  }}
                >
                  <Check className={cn("opacity-0", organization.id === organizationId && "opacity-100")} />
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
