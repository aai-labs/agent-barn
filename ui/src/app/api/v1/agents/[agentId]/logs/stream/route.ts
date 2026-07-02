export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const BACKEND_URL =
  process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";

export async function GET(
  request: Request,
  { params }: { params: Promise<{ agentId: string }> },
) {
  const { agentId } = await params;
  const { searchParams } = new URL(request.url);
  const tailLines = searchParams.get("tail_lines") ?? "0";

  const authorization = request.headers.get("Authorization");
  if (!authorization) {
    return new Response("Unauthorized", { status: 401 });
  }

  const upstream = await fetch(
    `${BACKEND_URL}/api/v1/agents/${agentId}/logs/stream?tail_lines=${tailLines}`,
    {
      headers: {
        Authorization: authorization,
        Accept: "text/event-stream",
      },
    },
  );

  if (!upstream.ok || !upstream.body) {
    return new Response(upstream.statusText, { status: upstream.status });
  }

  return new Response(upstream.body, {
    headers: {
      "Content-Type": "text/event-stream; charset=utf-8",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
      "Content-Encoding": "none",
      "X-Accel-Buffering": "no",
    },
  });
}
