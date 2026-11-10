"use client";

import { useState, useTransition } from "react";
import { Send, Sparkles } from "lucide-react";
import { Button, Spinner } from "@/components/ui";
import { composePack, publishPack } from "../actions";

export function ComposeButton({ projectId, handoverId, again, disabled }: {
  projectId: string;
  handoverId: string;
  again?: boolean;
  disabled?: boolean;
}) {
  const [pending, start] = useTransition();
  const [error, setError] = useState<string>();
  return (
    <span className="inline-flex flex-col gap-1">
      <Button
        variant={again ? "secondary" : "primary"}
        disabled={disabled || pending}
        onClick={() => start(async () => setError(await composePack(projectId, handoverId)))}
      >
        {pending ? <Spinner /> : <Sparkles className="size-4" aria-hidden="true" />}
        {pending ? "Starting…" : again ? "Write a new version" : "Write the pack"}
      </Button>
      {error && <span className="text-[12px] text-danger">{error}</span>}
    </span>
  );
}

export function PublishButton({ projectId, handoverId, version, to }: {
  projectId: string;
  handoverId: string;
  version: number;
  to: string;
}) {
  const [pending, start] = useTransition();
  const [error, setError] = useState<string>();
  return (
    <span className="inline-flex flex-col gap-1">
      <Button
        disabled={pending}
        onClick={() => {
          if (confirm(`Publish version ${version}? ${to} will be able to read it.`)) {
            start(async () => setError(await publishPack(projectId, handoverId)));
          }
        }}
      >
        {pending ? <Spinner /> : <Send className="size-4" aria-hidden="true" />}
        {pending ? "Publishing…" : `Publish version ${version}`}
      </Button>
      {error && <span className="text-[12px] text-danger">{error}</span>}
    </span>
  );
}
