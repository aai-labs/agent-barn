"use client";

import { useCurrentUser } from "@/auth/providers/user-context-provider";
import { SuperAdminDashboard } from "@/dashboard/components/super-admin-dashboard";
import { UserDashboard } from "@/dashboard/components/user-dashboard";

export default function Page() {
  const { user } = useCurrentUser();

  return (
    <div className="space-y-6 p-4 pt-2 md:p-6 md:pt-2">
      <div className="space-y-1">
        <h1 className="text-xl font-semibold tracking-tight">Dashboard</h1>
        <p className="text-sm text-muted-foreground">
          {user.isSuperuser
            ? "Super admin workspace for users and organizations."
            : "Your starter workspace."}
        </p>
      </div>
      {user.isSuperuser ? <SuperAdminDashboard /> : <UserDashboard />}
    </div>
  );
}
