"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";

import { AuthLoadingFallback } from "@/auth/components/auth-loading-fallback";

export function SessionExpirationHandler() {
  const router = useRouter();
  const queryClient = useQueryClient();

  useEffect(() => {
    queryClient.clear();
    router.replace("/login");
  }, [queryClient, router]);

  return <AuthLoadingFallback message="Session expired. Redirecting..." />;
}

