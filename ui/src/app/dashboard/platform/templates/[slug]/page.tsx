import { PlatformAdminOnly } from "@/auth/components/platform-admin-only";
import { PlatformTemplateEditorPage } from "@/features/platform-templates/components/platform-template-editor-page";

interface PageProps {
  params: Promise<{ slug: string }>;
}

export default async function PlatformTemplateDetailRoute({ params }: PageProps) {
  const { slug } = await params;

  return (
    <PlatformAdminOnly>
      <PlatformTemplateEditorPage slug={slug} />
    </PlatformAdminOnly>
  );
}
