import { AgentCommunicationConnectionDetailPage } from "@/features/agents/components/agent-communication-connection-detail-page";

interface PageProps {
  params: Promise<{ id: string; connectionId: string }>;
}

export default async function AgentCommunicationConnectionDetailRoute({ params }: PageProps) {
  const { id, connectionId } = await params;
  return <AgentCommunicationConnectionDetailPage agentId={id} connectionId={connectionId} />;
}
