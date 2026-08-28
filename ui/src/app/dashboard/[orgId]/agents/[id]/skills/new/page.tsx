import { AgentSkillNewPage } from "@/features/agents/components/agent-skill-new-page";

interface PageProps {
  params: Promise<{ id: string }>;
}

export default async function AgentSkillNewRoute({ params }: PageProps) {
  const { id } = await params;
  return <AgentSkillNewPage agentId={id} />;
}
