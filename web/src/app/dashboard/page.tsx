import Link from "next/link";
import { ArrowRight, Building, Users } from "lucide-react";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

export default function Page() {
  return (
    <div className="space-y-6 p-4 pt-2 md:p-6 md:pt-2">
      <div className="space-y-1">
        <h1 className="text-xl font-semibold tracking-tight">Dashboard</h1>
        <p className="text-sm text-muted-foreground">
          Starter kit workspace for users, and organizations.
        </p>
      </div>
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
    </div>
  );
}
