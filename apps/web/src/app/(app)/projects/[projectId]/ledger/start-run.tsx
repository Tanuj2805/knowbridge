"use client";

import { useState, useTransition } from "react";
import { Sparkles } from "lucide-react";
import { Button, Spinner } from "@/components/ui";
import { startRun } from "./actions";

export function StartRun({
  projectId,
  label,
  disabled,
  variant = "primary",
}: {
  projectId: string;
  label: string;
  disabled?: boolean;
  variant?: "primary" | "secondary";
}) {
  const [pending, start] = useTransition();
  const [error, setError] = useState<string>();
  return (
    <div className="flex flex-col items-end gap-1">
      <Button
        variant={variant}
        disabled={disabled || pending}
        aria-busy={pending}
        onClick={() => start(async () => setError(await startRun(projectId)))}
      >
        {pending || disabled && label.endsWith("…") ? <Spinner /> : <Sparkles className="size-4" aria-hidden="true" />}
        {pending ? "Starting…" : label}
      </Button>
      {error && <p className="text-[12px] text-danger max-w-xs text-right">{error}</p>}
    </div>
  );
}
