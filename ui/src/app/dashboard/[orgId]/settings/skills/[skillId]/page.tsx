import { SkillDetailPage } from "@/features/skills/components/skill-detail-page";

interface PageProps {
  params: Promise<{ skillId: string }>;
}

export default async function SkillDetailRoute({ params }: PageProps) {
  const { skillId } = await params;
  return <SkillDetailPage skillId={skillId} />;
}
