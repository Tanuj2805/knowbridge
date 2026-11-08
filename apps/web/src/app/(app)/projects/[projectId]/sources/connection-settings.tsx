"use client";

import { useActionState, useState } from "react";
import { SubmitButton } from "@/components/submit-button";
import { Button, ErrorNote, Input, Label } from "@/components/ui";
import { updateConnection } from "./actions";

/** Rotate a saved token (Jira or GitHub) or change which Jira issues are read. */
export function ConnectionSettings({
  projectId,
  sourceId,
  provider,
  jql,
}: {
  projectId: string;
  sourceId: string;
  provider: "jira" | "github";
  jql?: string;
}) {
  const [open, setOpen] = useState(false);
  const [state, action] = useActionState(updateConnection.bind(null, projectId, sourceId), undefined);

  if (!open) {
    return (
      <Button variant="quiet" size="sm" onClick={() => setOpen(true)}>
        {provider === "jira" ? "Jira settings" : "Change token"}
      </Button>
    );
  }
  return (
    <form action={action} className="mt-3 grid gap-3 rounded-lg border border-rule bg-paper-sunk/50 p-3 w-full max-w-md">
      {provider === "jira" && (
        <div>
          <Label htmlFor={`jql-${sourceId}`}>Which issues</Label>
          <Input id={`jql-${sourceId}`} name="jql" defaultValue={jql} autoComplete="off" />
        </div>
      )}
      <div>
        <Label htmlFor={`tok-${sourceId}`} hint={provider === "jira" ? "Leave empty to keep the current one." : undefined}>
          New {provider === "jira" ? "API" : "read-only"} token
        </Label>
        <Input id={`tok-${sourceId}`} name="token" type="password" autoComplete="new-password" />
      </div>
      {state?.error && <ErrorNote>{state.error}</ErrorNote>}
      {state?.ok && (
        <p role="status" className="text-sm text-accent">
          {state.ok}
        </p>
      )}
      <div className="flex gap-2">
        <SubmitButton size="sm" pendingText="Checking…">
          Save
        </SubmitButton>
        <Button type="button" variant="quiet" size="sm" onClick={() => setOpen(false)}>
          Close
        </Button>
      </div>
    </form>
  );
}
