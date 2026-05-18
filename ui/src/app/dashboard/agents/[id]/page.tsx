import { notFound } from "next/navigation";
import { AGENTS } from "@/features/agents/data";
import { AgentDetailPage } from "@/features/agents/components/agent-detail-page";

interface PageProps {
  params: Promise<{ id: string }>;
}

export default async function AgentPage({ params }: PageProps) {
  const { id } = await params;
  const agent = AGENTS.find((a) => a.id === id);
  if (!agent) notFound();
  return <AgentDetailPage agent={agent} />;
}

export function generateStaticParams() {
  return AGENTS.map((a) => ({ id: a.id }));
}
