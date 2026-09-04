"use client";

import { TemplateEditorPage } from "@/features/templates/components/template-editor-page";

export default function OrganizationTemplateNewRoute() {
  return <TemplateEditorPage scope={{ kind: "organization" }} isNew />;
}
