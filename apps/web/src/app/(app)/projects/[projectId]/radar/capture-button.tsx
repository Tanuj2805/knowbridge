"use client";

import { MessageSquarePlus } from "lucide-react";
import { useState, useTransition } from "react";
import { Button, Spinner } from "@/components/ui";
import { startCapture } from "./actions";

export function CaptureButton({ projectId, area, person }: { projectId: string; area: string; person: string }) {
  const [pending, start] = useTransition();
  const [error, setError] = useState<string>();
  const first = person.split(" ")[0];
  return (
    <div className="flex flex-col items-start gap-1 sm:items-end">
      <Button
        size="sm"
        variant="secondary"
        disabled={pending}
        aria-busy={pending}
        onClick={() => start(async () => setError(await startCapture(projectId, area)))}
      >
        {pending ? <Spinner /> : <MessageSquarePlus className="size-3.5" aria-hidden="true" />}
        {pending ? "Starting…" : `Capture ${first}'s knowledge`}
      </Button>
      {error && <p className="text-[12px] text-danger">{error}</p>}
    </div>
  );
}
