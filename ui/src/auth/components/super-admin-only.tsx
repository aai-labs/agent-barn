"use client";

import type { ReactNode } from "react";
import { ShieldAlert } from "lucide-react";

import { useCurrentUser } from "@/auth/providers/user-context-provider";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";

export function SuperAdminOnly({ children }: { children: ReactNode }) {
  const { user } = useCurrentUser();

  if (user.isSuperuser) {
    return <>{children}</>;
  }

  return (
    <div className="p-4 md:p-6">
      <Alert variant="destructive">
        <ShieldAlert className="size-4" />
        <AlertTitle>Platform admin access required</AlertTitle>
        <AlertDescription>
          You do not have permission to view this page.
        </AlertDescription>
      </Alert>
    </div>
  );
}
