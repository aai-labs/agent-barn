const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";

export async function GET() {
  const upstream = await fetch(`${backendUrl}/api/v1/llms.txt`, { cache: "no-store" });
  return new Response(upstream.body, {
    status: upstream.status,
    headers: { "Content-Type": "text/markdown; charset=utf-8" },
  });
}
