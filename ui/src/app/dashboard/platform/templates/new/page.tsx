import { PlatformAdminOnly } from "@/auth/components/platform-admin-only";
import { PlatformTemplateEditorPage } from "@/features/platform-templates/components/platform-template-editor-page";

export default function NewPlatformTemplateRoute() {
  return (
    <PlatformAdminOnly>
      <PlatformTemplateEditorPage isNew />
    </PlatformAdminOnly>
  );
}
