"use client";

import { useActionState } from "react";
import { SubmitButton } from "@/components/submit-button";
import { ErrorNote } from "@/components/ui";
import { loadDemo } from "./actions";

export function LoadDemo() {
  const [state, action] = useActionState(loadDemo, undefined);
  return (
    <form action={action} className="grid gap-2 justify-items-start">
      <SubmitButton variant="secondary" pendingText="Setting it up…">
        Load the Project Nimbus demo
      </SubmitButton>
      {state?.error && <ErrorNote>{state.error}</ErrorNote>}
    </form>
  );
}
