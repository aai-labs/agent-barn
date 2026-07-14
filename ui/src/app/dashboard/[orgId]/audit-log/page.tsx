import { Metadata } from "next";

import { AuditLogDashboard } from "@/features/audit-logs/components/audit-log-dashboard";

export const metadata: Metadata = {
  title: "Audit log | Agent Farm",
};

export default function AuditLogPage() {
  return <AuditLogDashboard scope="org" />;
}
