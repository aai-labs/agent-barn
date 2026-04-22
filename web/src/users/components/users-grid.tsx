"use client";

import { useDeferredValue, useState } from "react";
import { Loader2, Search, Shield, UserRound } from "lucide-react";

import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";

import { useInfiniteUsers } from "../hooks/use-infinite-users";

function formatDate(date: string | null | undefined) {
  if (!date) {
    return "Not verified";
  }
  return new Date(date).toLocaleString();
}

function LoadingCard() {
  return (
    <Card className="animate-pulse">
      <CardHeader>
        <div className="h-5 w-40 rounded-md bg-muted" />
        <div className="h-4 w-56 rounded-md bg-muted" />
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="h-4 w-28 rounded-md bg-muted" />
        <div className="h-4 w-36 rounded-md bg-muted" />
      </CardContent>
      <CardFooter>
        <div className="h-4 w-32 rounded-md bg-muted" />
      </CardFooter>
    </Card>
  );
}

export function UsersGrid() {
  const [search, setSearch] = useState("");
  const deferredSearch = useDeferredValue(search);
  const {
    users,
    total,
    hasNextPage,
    fetchNextPage,
    isFetchingNextPage,
    isLoading,
  } = useInfiniteUsers({ search: deferredSearch });

  return (
    <div className="space-y-5 p-4 pt-2 md:p-6 md:pt-2">
      <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Users</h1>
          <p className="text-sm text-muted-foreground">
            Super admin view of all users.
          </p>
        </div>
        <div className="relative w-full md:w-80">
          <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            className="pl-8"
            placeholder="Search by name or email"
            aria-label="Search users"
          />
        </div>
      </div>

      <p className="text-sm text-muted-foreground">
        {total} {total === 1 ? "user" : "users"}
      </p>

      {isLoading ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: 6 }).map((_, index) => (
            <LoadingCard key={index} />
          ))}
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {users.map((user) => (
            <Card key={user.id}>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <UserRound className="size-4 text-muted-foreground" />
                  <span>
                    {user.fullName || (user.isSuperuser ? "Super User" : "Unnamed user")}
                  </span>
                </CardTitle>
                <CardDescription>{user.email}</CardDescription>
              </CardHeader>
              <CardContent className="space-y-1 text-sm text-muted-foreground">
                <div className="flex items-center gap-2">
                  <Shield className="size-4" />
                  <span>{user.isSuperuser ? "Super admin" : "User"}</span>
                </div>
                <div>Created: {formatDate(user.createdAt)}</div>
              </CardContent>
              <CardFooter>
                <p className="text-xs text-muted-foreground">
                  Email verified: {formatDate(user.emailVerifiedAt)}
                </p>
              </CardFooter>
            </Card>
          ))}
        </div>
      )}

      {!isLoading && users.length === 0 ? (
        <Card>
          <CardHeader>
            <CardTitle>No users found</CardTitle>
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
              "Load more users"
            )}
          </Button>
        </div>
      ) : null}
    </div>
  );
}
