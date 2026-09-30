"use client";

import { useEffect } from "react";
import { useParams, useRouter } from "next/navigation";

import { useActiveOrgRole } from "@/features/organizations/hooks/use-active-org-role";
import { TemplateEditorPage } from "@/features/templates/components/template-editor-page";
import { templatesListHref } from "@/features/templates/scope";

export default function OrganizationTemplateNewRoute() {
  const router = useRouter();
  const params = useParams();
  const orgId = typeof params?.orgId === "string" ? params.orgId : null;
  const { canManage, selectedOrganization } = useActiveOrgRole();
  const isDenied = Boolean(selectedOrganization) && !canManage;

  useEffect(() => {
    if (isDenied) {
      router.replace(templatesListHref({ kind: "organization" }, orgId));
    }
  }, [isDenied, orgId, router]);

  if (isDenied) return null;
  return <TemplateEditorPage scope={{ kind: "organization" }} isNew canManage={canManage} />;
}
