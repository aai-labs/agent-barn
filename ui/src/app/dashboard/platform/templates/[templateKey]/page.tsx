import { PlatformAdminOnly } from "@/auth/components/platform-admin-only";
import { PlatformTemplateEditorPage } from "@/features/platform-templates/components/platform-template-editor-page";

interface PageProps {
  params: Promise<{ templateKey: string }>;
}

export default async function PlatformTemplateDetailRoute({ params }: PageProps) {
  const { templateKey } = await params;

  return (
    <PlatformAdminOnly>
      <PlatformTemplateEditorPage templateKey={templateKey} />
    </PlatformAdminOnly>
  );
}
