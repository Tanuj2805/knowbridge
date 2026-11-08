"use client";

import { useState, useTransition } from "react";
import { AutoRefresh } from "@/components/auto-refresh";
import { Button } from "@/components/ui";
import { buildSmartSearch } from "./evidence/actions";

/** Smart (meaning) search status, with a button for admins to index what's missing. */
export function SmartSearchStatus({
  projectId,
  ready,
  total,
  model,
  admin,
  external,
  keptPrivate,
}: {
  projectId: string;
  ready: number;
  total: number;
  model: string | null;
  admin: boolean;
  external: boolean;
  keptPrivate: number;
}) {
  const [pending, start] = useTransition();
  const [started, setStarted] = useState(false);
  const [error, setError] = useState<string>();

  if (!model) {
    return <p>Smart search is off, so search matches keywords only.</p>;
  }
  const indexable = total - keptPrivate;
  const missing = indexable - ready;
  const where = external ? "with Gemini" : "on this server";
  return (
    <div>
      <AutoRefresh active={started && missing > 0} every={4000} />
      <p>
        Smart search: <span className="text-ink font-medium">{ready.toLocaleString("en-IN")}</span> of{" "}
        {indexable.toLocaleString("en-IN")} items ready ({where}).
      </p>
      {external && (
        <p className="text-[13px] mt-1">
          Smart search sends masked text to Google (Gemini). Confidential items are never sent
          {keptPrivate > 0 ? `; ${keptPrivate} here stay keyword-only` : ""}.
        </p>
      )}
      {missing > 0 && admin && !started && (
        <Button
          variant="secondary"
          size="sm"
          className="mt-2"
          disabled={pending}
          onClick={() =>
            start(async () => {
              const err = await buildSmartSearch(projectId);
              setError(err);
              setStarted(!err);
            })
          }
        >
          Build smart search
        </Button>
      )}
      {started && missing > 0 && <p className="text-[13px] mt-1">Indexing… this page updates by itself.</p>}
      {error && <p className="text-[13px] text-danger mt-1">{error}</p>}
    </div>
  );
}
