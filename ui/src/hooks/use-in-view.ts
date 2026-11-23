"use client";

import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Whether an element is on screen (or within `rootMargin` of it), for work that only
 * matters while someone can see it, such as polling. Attach the returned ref to the
 * element. Reads as visible until the observer says otherwise, so a browser without
 * IntersectionObserver keeps doing the work.
 */
export function useInView<T extends Element>(rootMargin = "200px"): [(element: T | null) => void, boolean] {
  const [inView, setInView] = useState(true);
  const observerRef = useRef<IntersectionObserver | null>(null);

  const ref = useCallback(
    (element: T | null) => {
      observerRef.current?.disconnect();
      observerRef.current = null;
      if (!element || typeof IntersectionObserver === "undefined") return;
      const observer = new IntersectionObserver(([entry]) => setInView(entry.isIntersecting), { rootMargin });
      observer.observe(element);
      observerRef.current = observer;
    },
    [rootMargin],
  );

  useEffect(() => () => observerRef.current?.disconnect(), []);

  return [ref, inView];
}
