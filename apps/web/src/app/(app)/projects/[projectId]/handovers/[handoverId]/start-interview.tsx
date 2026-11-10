"use client";

import { useState, useTransition } from "react";
import { MessageSquareText } from "lucide-react";
import { Button, Spinner } from "@/components/ui";
import { startInterview } from "../actions";

export function StartInterview({ projectId, handoverId, disabled }: {
  projectId: string;
  handoverId: string;
  disabled?: boolean;
}) {
  const [pending, start] = useTransition();
  const [error, setError] = useState<string>();
  return (
    <div className="flex flex-col items-start gap-1">
      <Button
        disabled={disabled || pending}
        aria-busy={pending}
        onClick={() => start(async () => setError(await startInterview(projectId, handoverId)))}
      >
        {pending ? <Spinner /> : <MessageSquareText className="size-4" aria-hidden="true" />}
        {pending ? "Starting…" : "Prepare the Gap Interview"}
      </Button>
      {error && <p className="text-[12px] text-danger">{error}</p>}
    </div>
  );
}
