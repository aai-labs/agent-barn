"use client";

import { useParams } from "next/navigation";

import { useActiveOrgRole } from "@/features/organizations/hooks/use-active-org-role";
import { TemplateEditorPage } from "@/features/templates/components/template-editor-page";

export default function OrganizationTemplateDetailRoute() {
  const params = useParams();
  const templateKey = typeof params?.templateKey === "string" ? params.templateKey : null;
  const { canManage } = useActiveOrgRole();

  if (!templateKey) return null;
  return (
    <TemplateEditorPage
      scope={{ kind: "organization" }}
      templateKey={templateKey}
      canManage={canManage}
    />
  );
}
