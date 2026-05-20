import { AgentDetailPage } from "@/features/agents/components/agent-detail-page";

interface PageProps {
  params: Promise<{ id: string }>;
}

export default async function AgentPage({ params }: PageProps) {
  const { id } = await params;
  return <AgentDetailPage agentId={id} />;
}
