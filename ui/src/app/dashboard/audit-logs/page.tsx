import { Metadata } from "next";

import { SuperAdminOnly } from "@/auth/components/super-admin-only";
import { AuditLogDashboard } from "@/features/audit-logs/components/audit-log-dashboard";

export const metadata: Metadata = {
  title: "Audit logs | Agent Farm",
};

export default function AllOrgsAuditLogPage() {
  return (
    <SuperAdminOnly>
      <AuditLogDashboard scope="all" />
    </SuperAdminOnly>
  );
}
