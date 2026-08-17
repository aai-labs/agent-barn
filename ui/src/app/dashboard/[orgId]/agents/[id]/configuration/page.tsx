import { AgentConfigurationPage } from "@/features/agents/components/agent-configuration-page";

interface PageProps {
  params: Promise<{ id: string }>;
}

export default async function AgentConfigurationRoute({ params }: PageProps) {
  const { id } = await params;
  return <AgentConfigurationPage agentId={id} />;
}
