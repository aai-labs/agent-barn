"use client";

import { useLinkStatus } from "next/link";

/**
 * A thin bar along the bottom of a navigation link while its click waits on the server,
 * which happens when the click lands before Next.js finished prefetching the route. It
 * must render inside the `<Link>`, which needs `position: relative`. Always mounted and
 * shown only after a short delay (globals.css), so prefetched clicks never flash it and
 * it never shifts the layout.
 */
export function LinkPendingHint() {
  const { pending } = useLinkStatus();
  return <span aria-hidden className="af-link-pending" data-pending={pending} />;
}
