"use client";

import type { ReactNode } from "react";
import { useActionState } from "react";
import { SubmitButton } from "@/components/submit-button";
import { ErrorNote, Input, Label, RequiredNote, Textarea } from "@/components/ui";
import { createProject } from "./actions";

/** Name and a line about the project. On success the new project opens. */
export function NewProjectForm({ cancel }: { cancel?: ReactNode }) {
  const [state, action] = useActionState(createProject, undefined);
  return (
    <form action={action} className="grid gap-4">
      <RequiredNote />
      <div>
        <Label htmlFor="name" required>
          Project name
        </Label>
        <Input
          id="name"
          name="name"
          required
          minLength={2}
          placeholder="e.g. Fest app 2026"
          autoComplete="off"
          autoFocus
        />
      </div>
      <div>
        <Label htmlFor="description" hint="Optional. One or two lines; the successor reads this first.">
          What is it?
        </Label>
        <Textarea id="description" name="description" rows={3} placeholder="e.g. The web app for our college fest: registrations, payments and tickets." />
      </div>
      {state?.error && <ErrorNote>{state.error}</ErrorNote>}
      <div className="flex items-center justify-end gap-2 pt-1">
        {cancel}
        <SubmitButton pendingText="Creating…">Create project</SubmitButton>
      </div>
    </form>
  );
}
