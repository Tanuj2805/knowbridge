"use client";

import { useActionState } from "react";
import { SubmitButton } from "@/components/submit-button";
import { ErrorNote, Input, Label, Textarea } from "@/components/ui";
import { createProject } from "./actions";

export function NewProjectForm() {
  const [state, action] = useActionState(createProject, undefined);
  return (
    <form action={action} className="grid gap-4 max-w-xl">
      <div>
        <Label htmlFor="name">Project name</Label>
        <Input id="name" name="name" required minLength={2} placeholder="e.g. Fest app 2026" autoComplete="off" />
      </div>
      <div>
        <Label htmlFor="description" hint="One or two lines. The successor reads this first.">
          What is it?
        </Label>
        <Textarea id="description" name="description" rows={2} />
      </div>
      {state?.error && <ErrorNote>{state.error}</ErrorNote>}
      <div>
        <SubmitButton pendingText="Creating…">Create project</SubmitButton>
      </div>
    </form>
  );
}
