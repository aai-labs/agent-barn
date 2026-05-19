import Link from "next/link";

export default function NotFound() {
  return (
    <div
      className="min-h-screen flex flex-col items-center justify-center px-6"
      style={{ background: "var(--bg)" }}
    >
      <div className="text-center max-w-sm">
        <div
          className="text-[80px] font-semibold tracking-[-0.04em] leading-none mb-4"
          style={{ color: "var(--line-strong)" }}
        >
          404
        </div>
        <h1
          className="text-[22px] font-semibold tracking-tight mb-2"
          style={{ color: "var(--ink)" }}
        >
          Page not found
        </h1>
        <p className="text-[14.5px] leading-[1.55] mb-8" style={{ color: "var(--ink-3)" }}>
          The page you&apos;re looking for doesn&apos;t exist or was moved.
        </p>
        <Link href="/dashboard" className="af-btn af-btn-primary">
          Back to dashboard
        </Link>
      </div>
    </div>
  );
}
