"use client";

import { useDeferredValue, useState } from "react";
import { Building, Loader2, Search, UserRound } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";

import { useInfiniteOrganizations } from "../hooks/use-infinite-organizations";

function LoadingCard() {
  return (
    <Card className="animate-pulse">
      <CardHeader>
        <div className="h-5 w-40 rounded-md bg-muted" />
        <div className="h-4 w-52 rounded-md bg-muted" />
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="h-4 w-36 rounded-md bg-muted" />
        <div className="h-4 w-28 rounded-md bg-muted" />
      </CardContent>
      <CardFooter>
        <div className="h-4 w-48 rounded-md bg-muted" />
      </CardFooter>
    </Card>
  );
}

export function OrganizationsGrid() {
  const [search, setSearch] = useState("");
  const deferredSearch = useDeferredValue(search);
  const {
    organizations,
    total,
    hasNextPage,
    fetchNextPage,
    isFetchingNextPage,
    isLoading,
  } = useInfiniteOrganizations({ search: deferredSearch });

  return (
    <div className="space-y-5 p-4 pt-2 md:p-6 md:pt-2">
      <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Organizations</h1>
          <p className="text-sm text-muted-foreground">
            Super admin view of all organizations.
          </p>
        </div>
        <div className="relative w-full md:w-80">
          <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            className="pl-8"
            placeholder="Search by name, owner, or description"
            aria-label="Search organizations"
          />
        </div>
      </div>

      <p className="text-sm text-muted-foreground">
        {total} {total === 1 ? "organization" : "organizations"}
      </p>

      {isLoading ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: 6 }).map((_, index) => (
            <LoadingCard key={index} />
          ))}
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {organizations.map((organization) => (
            <Card key={organization.id}>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Building className="size-4 text-muted-foreground" />
                  <span>{organization.name}</span>
                </CardTitle>
                <CardDescription>
                  {organization.description || "No description"}
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-1 text-sm text-muted-foreground">
                <div className="flex items-center gap-2">
                  <UserRound className="size-4" />
                  <span>{organization.ownerName || "No owner name"}</span>
                </div>
                <div>{organization.ownerEmail || "No owner email"}</div>
              </CardContent>
              <CardFooter>
                <p className="text-xs text-muted-foreground">
                  Created: {new Date(organization.createdAt).toLocaleString()}
                </p>
              </CardFooter>
            </Card>
          ))}
        </div>
      )}

      {!isLoading && organizations.length === 0 ? (
        <Card>
          <CardHeader>
            <CardTitle>No organizations found</CardTitle>
            <CardDescription>Try a different search term.</CardDescription>
          </CardHeader>
        </Card>
      ) : null}

      {hasNextPage ? (
        <div className="flex justify-center pb-4">
          <Button
            variant="outline"
            onClick={() => fetchNextPage()}
            disabled={isFetchingNextPage}
          >
            {isFetchingNextPage ? (
              <>
                <Loader2 className="size-4 animate-spin" />
                Loading more
              </>
            ) : (
              "Load more organizations"
            )}
          </Button>
        </div>
      ) : null}
    </div>
  );
}
