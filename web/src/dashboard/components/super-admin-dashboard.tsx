"use client";

import Link from "next/link";
import { ArrowRight, Building, Users } from "lucide-react";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

export function SuperAdminDashboard() {
  return (
    <div className="grid gap-4 md:grid-cols-2">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Users className="size-4 text-muted-foreground" />
            Users
          </CardTitle>
          <CardDescription>
            Browse all users with search and infinite loading.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Link
            href="/dashboard/users"
            className="inline-flex items-center gap-2 text-sm font-medium text-primary hover:underline"
          >
            Open users page <ArrowRight className="size-4" />
          </Link>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Building className="size-4 text-muted-foreground" />
            Organizations
          </CardTitle>
          <CardDescription>
            Browse all organizations with search and infinite loading.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Link
            href="/dashboard/organizations"
            className="inline-flex items-center gap-2 text-sm font-medium text-primary hover:underline"
          >
            Open organizations page <ArrowRight className="size-4" />
          </Link>
        </CardContent>
      </Card>
    </div>
  );
}
