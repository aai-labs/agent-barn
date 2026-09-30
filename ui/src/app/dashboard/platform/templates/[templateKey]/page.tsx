import { PlatformAdminOnly } from "@/auth/components/platform-admin-only";
import { TemplateEditorPage } from "@/features/templates/components/template-editor-page";

interface PageProps {
  params: Promise<{ templateKey: string }>;
}

export default async function PlatformTemplateDetailRoute({ params }: PageProps) {
  const { templateKey } = await params;

  return (
    <PlatformAdminOnly>
      <TemplateEditorPage scope={{ kind: "platform" }} templateKey={templateKey} />
    </PlatformAdminOnly>
  );
}
