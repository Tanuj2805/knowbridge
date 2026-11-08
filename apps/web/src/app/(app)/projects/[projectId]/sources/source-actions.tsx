"use client";

import { useState, useTransition } from "react";
import { Button } from "@/components/ui";
import { removeSource, syncSource } from "./actions";

export function SourceActions({
  projectId,
  sourceId,
  name,
  busy,
  live = false,
}: {
  projectId: string;
  sourceId: string;
  name: string;
  busy: boolean;
  live?: boolean;
}) {
  const [pending, start] = useTransition();
  const [error, setError] = useState<string>();
  return (
    <div className="flex flex-col items-end gap-1">
      <div className="flex gap-1">
        <Button
          variant="secondary"
          size="sm"
          disabled={busy || pending}
          onClick={() => start(async () => setError(await syncSource(projectId, sourceId)))}
        >
          {live ? "Check for changes" : "Sync now"}
        </Button>
        {live && (
          <Button
            variant="quiet"
            size="sm"
            disabled={busy || pending}
            title="Re-read everything, and notice items deleted at the source"
            onClick={() => start(async () => setError(await syncSource(projectId, sourceId, true)))}
          >
            Full re-sync
          </Button>
        )}
        <Button
          variant="quiet"
          size="sm"
          disabled={pending}
          onClick={() => {
            if (
              confirm(
                `Remove “${name}”? Its evidence is deleted, and any claim that cited it loses that citation.`,
              )
            ) {
              start(() => removeSource(projectId, sourceId));
            }
          }}
        >
          Remove
        </Button>
      </div>
      {error && <p className="text-[12px] text-danger">{error}</p>}
    </div>
  );
}
