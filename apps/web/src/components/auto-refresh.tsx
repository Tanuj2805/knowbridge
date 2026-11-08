"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

/** Re-renders the server page every few seconds while something is in progress. */
export function AutoRefresh({ active, every = 3000 }: { active: boolean; every?: number }) {
  const router = useRouter();
  useEffect(() => {
    if (!active) return;
    const id = setInterval(() => router.refresh(), every);
    return () => clearInterval(id);
  }, [active, every, router]);
  return null;
}
