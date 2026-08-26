import { Suspense } from "react";

import { SkillDetailPage } from "@/features/skills/components/skill-detail-page";

interface PageProps {
  params: Promise<{ skillId: string }>;
}

export default async function SkillDetailRoute({ params }: PageProps) {
  const { skillId } = await params;
  return (
    <Suspense fallback={null}>
      <SkillDetailPage skillId={skillId} />
    </Suspense>
  );
}
