"use client";

import { RefreshCw } from "lucide-react";
import { useState, useTransition } from "react";
import { Button, Spinner } from "@/components/ui";
import { regroupAreas } from "./actions";

export function RegroupButton({ projectId }: { projectId: string }) {
  const [pending, start] = useTransition();
  const [error, setError] = useState<string>();
  return (
    <div className="flex flex-col items-start gap-1 sm:items-end">
      <Button
        size="sm"
        variant="quiet"
        disabled={pending}
        aria-busy={pending}
        onClick={() => start(async () => setError(await regroupAreas(projectId)))}
      >
        {pending ? <Spinner /> : <RefreshCw className="size-3.5" aria-hidden="true" />}
        Regroup areas
      </Button>
      {error && <p className="text-[12px] text-danger">{error}</p>}
    </div>
  );
}
