export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const BACKEND_URL =
  process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";

/** Streams a WhatsApp pairing attempt through unbuffered, like the Agent log stream. */
export async function POST(
  request: Request,
  {
    params,
  }: {
    params: Promise<{ organizationId: string; agentId: string; connectionId: string }>;
  },
) {
  const { organizationId, agentId, connectionId } = await params;

  const authorization = request.headers.get("Authorization");
  if (!authorization) {
    return new Response("Unauthorized", { status: 401 });
  }

  const upstream = await fetch(
    `${BACKEND_URL}/api/v1/organizations/${organizationId}/agents/${agentId}/connections/${connectionId}/whatsapp-pairing`,
    {
      method: "POST",
      headers: {
        Authorization: authorization,
        Accept: "text/event-stream",
      },
      signal: request.signal,
    },
  );

  if (!upstream.ok || !upstream.body) {
    // Keep the API's JSON error body so the dialog can show its detail.
    return new Response(await upstream.text(), {
      status: upstream.status,
      headers: { "Content-Type": upstream.headers.get("Content-Type") ?? "text/plain" },
    });
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
