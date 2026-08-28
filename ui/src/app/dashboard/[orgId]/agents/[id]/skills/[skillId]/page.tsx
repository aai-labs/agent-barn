import { AgentSkillDetailPage } from "@/features/agents/components/agent-skill-detail-page";

interface PageProps {
  params: Promise<{ id: string; skillId: string }>;
}

export default async function AgentSkillDetailRoute({ params }: PageProps) {
  const { id, skillId } = await params;
  return <AgentSkillDetailPage agentId={id} skillId={skillId} />;
}
