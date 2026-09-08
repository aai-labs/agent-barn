import { PlatformAdminOnly } from "@/auth/components/platform-admin-only";
import { TemplateEditorPage } from "@/features/templates/components/template-editor-page";

export default function NewPlatformTemplateRoute() {
  return (
    <PlatformAdminOnly>
      <TemplateEditorPage scope={{ kind: "platform" }} isNew />
    </PlatformAdminOnly>
  );
}
